from django.db import models

from posthog.models.utils import UUIDModel
from posthog.models.team import Team

from posthog.helpers.encrypted_fields import EncryptedJSONStringField

from typing import Self
from enum import Enum


class DateRangeExportSource(str, Enum):
    MIXPANEL = "mixpanel"
    AMPLITUDE = "amplitude"


class ContentType(str, Enum):
    MIXPANEL = "mixpanel"
    CAPTURED = "captured"
    AMPLITUDE = "amplitude"

    def serialize(self) -> dict:
        return {"type": self.value}


class BatchImport(UUIDModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        PAUSED = "paused", "Paused"
        RUNNING = "running", "Running"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_by_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    lease_id = models.TextField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    status = models.TextField(choices=Status.choices, default=Status.RUNNING)
    # Status message to save to the job, so that a developer can debug why a commit might have failed
    # Not displayed to the user
    status_message = models.TextField(null=True, blank=True)
    # Status message to be displayed to the user
    display_status_message = models.TextField(null=True, blank=True)
    state = models.JSONField(null=True, blank=True)
    import_config = models.JSONField()
    secrets = EncryptedJSONStringField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_builder = BatchImportConfigBuilder(self, initialize_empty=not self.import_config)

    @property
    def config(self) -> "BatchImportConfigBuilder":
        return self._config_builder


# Mostly used for manual job creation
class BatchImportConfigBuilder:
    def __init__(self, batch_import: BatchImport, initialize_empty: bool = True):
        self.batch_import = batch_import
        if initialize_empty:
            self.batch_import.import_config = {}
            self.batch_import.secrets = {}

    def json_lines(self, content_type: ContentType, skip_blanks: bool = True) -> Self:
        self.batch_import.import_config["data_format"] = {
            "type": "json_lines",
            "skip_blanks": skip_blanks,
            "content": content_type.serialize(),
        }
        return self

    def from_folder(self, path: str) -> Self:
        self.batch_import.import_config["source"] = {"type": "folder", "path": path}
        return self

    def from_urls(
        self, urls: list[str], urls_key: str = "urls", allow_internal_ips: bool = False, timeout_seconds: int = 30
    ) -> Self:
        self.batch_import.import_config["source"] = {
            "type": "url_list",
            "urls_key": urls_key,
            "allow_internal_ips": allow_internal_ips,
            "timeout_seconds": timeout_seconds,
        }
        self.batch_import.secrets[urls_key] = urls
        return self

    def from_s3(
        self,
        bucket: str,
        prefix: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        access_key_id_key: str = "aws_access_key_id",
        secret_access_key_key: str = "aws_secret_access_key",
    ) -> Self:
        self.batch_import.import_config["source"] = {
            "type": "s3",
            "bucket": bucket,
            "prefix": prefix,
            "region": region,
            "access_key_id_key": access_key_id_key,
            "secret_access_key_key": secret_access_key_key,
        }
        self.batch_import.secrets[access_key_id_key] = access_key_id
        self.batch_import.secrets[secret_access_key_key] = secret_access_key
        return self

    def from_date_range(
        self,
        start_date: str,
        end_date: str,
        access_key: str,
        secret_key: str,
        export_source: DateRangeExportSource,
        access_key_key: str = "api_key",
        secret_key_key: str = "secret_key",
    ) -> Self:
        # there is a bunch of annoying business logic around how each endpoint behaves (what requests an endpoint expects, what it responds with, etc.)
        # jam a bunch of that messy configuration here to keep it off the batch-import-worker and out of the client
        match export_source:
            case DateRangeExportSource.AMPLITUDE:
                base_url = "https://amplitude.com/api/2/export"
                auth_config = {
                    "type": "basic_auth",
                    "username_secret": access_key_key,
                    "password_secret": secret_key_key,
                }
                additional_config = {
                    "extractor_type": "zip_gzip_json",
                    "is_compressed": True,
                    "start_qp": "start",
                    "end_qp": "end",
                    "date_format": "%Y%m%dT%H",
                    # The smallest duration we can request from amplitude is 1 hour at a time
                    "interval_duration": 3600,
                    "timeout_seconds": 180,
                }
            case DateRangeExportSource.MIXPANEL:
                base_url = "https://data.mixpanel.com/api/2.0/export"
                auth_config = {
                    "type": "mixpanel_auth",
                    "secret_key_secret": secret_key_key,
                }
                additional_config = {
                    "extractor_type": "plain_gzip",
                    "is_compressed": True,
                    "start_qp": "from_date",
                    "end_qp": "to_date",
                    "date_format": "%Y-%m-%d",
                    # Smallest duration that we can request form mixpanel is 1 day at a time :(
                    # folks with bigger exports will almost certainly need to use s3/static storage source instead
                    # as we can't reasonably download a day's worth of big customer's data to our workers at a time
                    "interval_duration": 86400,
                    # Mixpanel endpoint is slow and can only request a day at a time at minimum so we need a long timeout
                    "timeout_seconds": 300,
                    "headers": {"Accept-Encoding": "gzip"},
                }
            case _:
                raise ValueError(f"Unsupported export source: {export_source}")

        self.batch_import.import_config["source"] = {
            "type": "date_range_export",
            "start": start_date,
            "end": end_date,
            "auth": auth_config,
            "base_url": base_url,
            **additional_config,
        }
        self.batch_import.secrets[access_key_key] = access_key
        self.batch_import.secrets[secret_key_key] = secret_key
        return self

    def to_stdout(self, as_json: bool = True) -> Self:
        self.batch_import.import_config["sink"] = {"type": "stdout", "as_json": as_json}
        return self

    def to_file(self, path: str, as_json: bool = True, cleanup: bool = False) -> Self:
        self.batch_import.import_config["sink"] = {"type": "file", "path": path, "as_json": as_json, "cleanup": cleanup}
        return self

    def to_kafka(self, topic: str, send_rate: int, transaction_timeout_seconds: int) -> Self:
        self.batch_import.import_config["sink"] = {
            "type": "kafka",
            "topic": topic,
            "send_rate": send_rate,
            "transaction_timeout_seconds": transaction_timeout_seconds,
        }
        return self

    def to_noop(self) -> Self:
        self.batch_import.import_config["sink"] = {"type": "noop"}
        return self
