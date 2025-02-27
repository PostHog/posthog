from django.db import models

from posthog.models.utils import UUIDModel
from posthog.models.team import Team

from posthog.helpers.encrypted_fields import EncryptedJSONStringField

from typing import Self
from enum import Enum


class ContentType(str, Enum):
    MIXPANEL = "mixpanel"
    CAPTURED = "captured"

    def serialize(self) -> dict:
        return {"type": self.value}


class BatchImport(UUIDModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        PAUSED = "paused", "Paused"
        RUNNING = "running", "Running"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    lease_id = models.TextField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    status = models.TextField(choices=Status.choices, default=Status.RUNNING)
    status_message = models.TextField(null=True, blank=True)
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
