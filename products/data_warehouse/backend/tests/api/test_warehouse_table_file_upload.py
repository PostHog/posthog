import io

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

import pandas as pd
from parameterized import parameterized
from rest_framework import status

from posthog.rate_limit import FileUploadBurstThrottle, FileUploadSustainedThrottle

from products.data_warehouse.backend.presentation.views.table import TableViewSet
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

VIEW_MODULE = "products.data_warehouse.backend.presentation.views.table"
MODEL_MODULE = "products.warehouse_sources.backend.models.table"

# Stand-in for what `DataWarehouseTable.get_columns()` reads off the object in place — patched so the
# create tests never reach chdb/ClickHouse, which can't introspect a fake S3 object.
FAKE_COLUMNS = {
    "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "total": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
}


class _CapturingBuffer(io.BytesIO):
    """A BytesIO that publishes its contents to a sink on close, so the endpoint's
    context-managed write is captured once the file handle is closed."""

    def __init__(self, sink: dict[str, bytes], path: str) -> None:
        super().__init__()
        self._sink = sink
        self._path = path

    def close(self) -> None:
        self._sink[self._path] = self.getvalue()
        super().close()


class _FakeS3:
    """Captures what the endpoint writes, standing in for the object store boundary."""

    def __init__(self, *, exists_result: bool = True) -> None:
        self.written: dict[str, bytes] = {}
        self.removed: list[str] = []
        self._exists_result = exists_result

    def open(self, path: str, mode: str) -> io.BytesIO:
        return _CapturingBuffer(self.written, path)

    def exists(self, path: str) -> bool:
        return self._exists_result

    def rm(self, path: str) -> None:
        self.removed.append(path)


@override_settings(DATAWAREHOUSE_BUCKET="test-bucket")
class TestWarehouseTableUploadFile(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.pk}/warehouse_tables/upload_file/"
        self.s3 = _FakeS3()

    def _upload(self, **data):
        with patch(f"{VIEW_MODULE}.get_s3_client", return_value=self.s3):
            return self.client.post(self.url, data, format="multipart")

    def test_stores_file_under_a_team_scoped_key_and_returns_the_upload_id(self) -> None:
        response = self._upload(
            file=SimpleUploadedFile("data.csv", b"a,b\n1,2\n", content_type="text/csv"),
            file_format="csv",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["filename"] == "data.csv"
        assert body["file_format"] == "csv"
        assert body["size_bytes"] == 8

        [written_path] = self.s3.written
        assert written_path == f"test-bucket/file_uploads/team_{self.team.pk}/{body['upload_id']}/data.csv"
        assert self.s3.written[written_path] == b"a,b\n1,2\n"

    def test_xlsx_is_converted_to_parquet_and_stored(self) -> None:
        # ClickHouse can't read Excel, so the endpoint converts the workbook to Parquet and reports
        # 'parquet' + a .parquet name. Returning 'xlsx' here would make create_from_upload 400.
        xlsx = io.BytesIO()
        pd.DataFrame({"id": [1, 2], "total": [10, 20]}).to_excel(xlsx, index=False, engine="openpyxl")

        response = self._upload(
            file=SimpleUploadedFile(
                "report.xlsx",
                xlsx.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            file_format="xlsx",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["file_format"] == "parquet"
        assert body["filename"] == "report.parquet"

        [written_path] = self.s3.written
        assert written_path == f"test-bucket/file_uploads/team_{self.team.pk}/{body['upload_id']}/report.parquet"
        restored = pd.read_parquet(io.BytesIO(self.s3.written[written_path]))
        assert list(restored.columns) == ["id", "total"]
        assert restored["id"].tolist() == [1, 2]

    def test_invalid_xlsx_is_rejected_without_storing_anything(self) -> None:
        response = self._upload(
            file=SimpleUploadedFile("bad.xlsx", b"not really a workbook", content_type="application/octet-stream"),
            file_format="xlsx",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Excel" in response.json()["message"]
        assert self.s3.written == {}

    def test_filename_cannot_escape_the_team_prefix(self) -> None:
        response = self._upload(
            file=SimpleUploadedFile("../../secrets.csv", b"a\n1\n", content_type="text/csv"),
            file_format="csv",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        [written_path] = self.s3.written
        assert ".." not in written_path
        assert written_path.startswith(f"test-bucket/file_uploads/team_{self.team.pk}/")

    @parameterized.expand(
        [
            ("unsupported_format", "tsv", "Invalid format"),
            ("empty_format", "", "Invalid format"),
        ]
    )
    def test_rejects_bad_format(self, _name: str, file_format: str, expected: str) -> None:
        response = self._upload(
            file=SimpleUploadedFile("data.csv", b"a\n1\n", content_type="text/csv"),
            file_format=file_format,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected in response.json()["message"]

    def test_rejects_missing_file(self) -> None:
        response = self._upload(file_format="csv")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["message"] == "No file provided"

    def test_rejects_a_file_over_the_size_cap(self) -> None:
        with patch(f"{VIEW_MODULE}.MAX_FILE_UPLOAD_SIZE_BYTES", 4):
            response = self._upload(
                file=SimpleUploadedFile("data.csv", b"way too much data", content_type="text/csv"),
                file_format="csv",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "File size exceeds the maximum" in response.json()["message"]
        assert self.s3.written == {}

    def test_rejects_an_oversized_request_body_before_storing_anything(self) -> None:
        # Guards the Content-Length pre-check that bounds the whole body before the multipart parser
        # spools parts to disk — dropping it would let a large body through to be written.
        with patch(f"{VIEW_MODULE}.MAX_UPLOAD_REQUEST_BODY_BYTES", 4):
            response = self._upload(
                file=SimpleUploadedFile("data.csv", b"a\n1\n", content_type="text/csv"),
                file_format="csv",
            )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "Upload exceeds the maximum" in response.json()["message"]
        assert self.s3.written == {}

    def test_rejects_more_than_one_file_part(self) -> None:
        with patch(f"{VIEW_MODULE}.get_s3_client", return_value=self.s3):
            response = self.client.post(
                self.url,
                {
                    "file": [
                        SimpleUploadedFile("a.csv", b"a\n1\n", content_type="text/csv"),
                        SimpleUploadedFile("b.csv", b"b\n2\n", content_type="text/csv"),
                    ],
                    "file_format": "csv",
                },
                format="multipart",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["message"] == "Upload one file per request."
        assert self.s3.written == {}

    @override_settings(DATAWAREHOUSE_BUCKET=None)
    def test_rejects_when_object_storage_is_unavailable(self) -> None:
        response = self._upload(
            file=SimpleUploadedFile("data.csv", b"a\n1\n", content_type="text/csv"),
            file_format="csv",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Object storage" in response.json()["message"]

    def test_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("data.csv", b"a\n1\n"), "file_format": "csv"},
            format="multipart",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert self.s3.written == {}


@override_settings(DATAWAREHOUSE_BUCKET="test-bucket", DATAWAREHOUSE_BUCKET_DOMAIN="warehouse.posthog.test")
class TestCreateTableFromUpload(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.upload_url = f"/api/environments/{self.team.pk}/warehouse_tables/upload_file/"
        self.create_url = f"/api/environments/{self.team.pk}/warehouse_tables/create_from_upload/"

    def _upload(self, filename: str = "orders.csv", file_format: str = "csv") -> str:
        with patch(f"{VIEW_MODULE}.get_s3_client", return_value=_FakeS3()):
            response = self.client.post(
                self.upload_url,
                {"file": SimpleUploadedFile(filename, b"id,total\n1,9\n"), "file_format": file_format},
                format="multipart",
            )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["upload_id"]

    def _create(self, *, exists: bool = True, **payload):
        with (
            patch(f"{VIEW_MODULE}.get_s3_client", return_value=_FakeS3(exists_result=exists)),
            patch(f"{MODEL_MODULE}.DataWarehouseTable.get_columns", return_value=dict(FAKE_COLUMNS)),
            # Background column validation runs eagerly under test and would re-query the (faked) S3
            # table, stamping `valid` onto each column. It's out of scope for these wiring tests, so
            # keep it from mutating the columns the create endpoint just persisted.
            patch(f"{VIEW_MODULE}.validate_data_warehouse_table_columns.delay"),
        ):
            return self.client.post(f"{self.create_url}?include_columns=false", data=payload, format="json")

    def test_an_uploaded_file_becomes_a_self_managed_table(self) -> None:
        # The wiring guard for the two-step contract: the upload endpoint's `upload_id` has to be
        # accepted by create_from_upload, and the result has to be a self-managed table (no source,
        # queried in place from our own bucket) rather than a pipeline ExternalDataSource.
        upload_id = self._upload()

        response = self._create(upload_id=upload_id, filename="orders.csv", file_format="csv", table_name="orders")

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        table = DataWarehouseTable.objects.get(id=response.json()["id"])
        assert table.name == "orders"
        assert table.external_data_source is None
        assert table.credential is None
        assert table.format == "CSVWithNames"
        assert (
            table.url_pattern
            == f"https://warehouse.posthog.test/file_uploads/team_{self.team.pk}/{upload_id}/orders.csv"
        )
        assert table.columns == FAKE_COLUMNS
        # No pipeline source is created — this is the whole point of the self-managed shape.
        assert ExternalDataSource.objects.count() == 0

    @parameterized.expand(
        [
            ("csv", "CSVWithNames"),
            ("json", "JSONEachRow"),
            ("parquet", "Parquet"),
        ]
    )
    def test_file_format_maps_to_table_format(self, file_format: str, expected_format: str) -> None:
        upload_id = self._upload(filename=f"data.{file_format}", file_format=file_format)

        response = self._create(
            upload_id=upload_id,
            filename=f"data.{file_format}",
            file_format=file_format,
            table_name=f"data_{file_format}",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        table = DataWarehouseTable.objects.get(id=response.json()["id"])
        assert table.format == expected_format

    def test_url_pattern_is_scoped_to_the_requesting_team(self) -> None:
        # The read location is always built from the caller's own team, so a client-supplied upload_id
        # can only ever resolve inside that team's folder.
        upload_id = self._upload()

        response = self._create(upload_id=upload_id, filename="orders.csv", file_format="csv", table_name="orders")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        table = DataWarehouseTable.objects.get(id=response.json()["id"])
        assert f"/team_{self.team.pk}/" in table.url_pattern

    def test_rejects_a_duplicate_table_name(self) -> None:
        upload_id = self._upload()
        first = self._create(upload_id=upload_id, filename="orders.csv", file_format="csv", table_name="orders")
        assert first.status_code == status.HTTP_201_CREATED, first.json()

        second = self._create(upload_id=upload_id, filename="orders.csv", file_format="csv", table_name="orders")
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in second.json()["message"]

    def test_rejects_an_invalid_table_name(self) -> None:
        upload_id = self._upload()
        response = self._create(upload_id=upload_id, filename="orders.csv", file_format="csv", table_name="1-bad name")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_when_the_uploaded_file_is_missing(self) -> None:
        upload_id = self._upload()
        response = self._create(
            upload_id=upload_id, filename="orders.csv", file_format="csv", table_name="orders", exists=False
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not found" in response.json()["message"]
        assert DataWarehouseTable.objects.count() == 0


@override_settings(DATAWAREHOUSE_BUCKET="test-bucket", DATAWAREHOUSE_BUCKET_DOMAIN="warehouse.posthog.test")
class TestWarehouseTableDeleteRemovesHostedFile(APIBaseTest):
    def _delete(self, table: DataWarehouseTable) -> tuple[int, list[str]]:
        s3 = _FakeS3()
        with patch(f"{VIEW_MODULE}.get_s3_client", return_value=s3):
            response = self.client.delete(f"/api/environments/{self.team.pk}/warehouse_tables/{table.id}")
        return response.status_code, s3.removed

    def test_deleting_a_hosted_upload_removes_its_backing_file(self) -> None:
        # The whole point of the fix: a self-managed table whose file we host must have that object
        # removed from our bucket on delete, not just have its row soft-deleted.
        upload_id = "11111111-1111-1111-1111-111111111111"
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="orders",
            format="CSVWithNames",
            url_pattern=f"https://warehouse.posthog.test/file_uploads/team_{self.team.pk}/{upload_id}/orders.csv",
            columns={},
        )

        status_code, removed = self._delete(table)

        assert status_code == status.HTTP_204_NO_CONTENT
        assert removed == [f"test-bucket/file_uploads/team_{self.team.pk}/{upload_id}/orders.csv"]

    def test_deleting_a_linked_bucket_table_leaves_the_customer_file_untouched(self) -> None:
        # A self-managed table pointing at a customer's own bucket carries a credential and a foreign
        # host — deleting its file would destroy data on infra we don't own, so we must never touch it.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="orders",
            format="CSVWithNames",
            url_pattern="https://customer-bucket.s3.amazonaws.com/exports/orders.csv",
            credential=credential,
            columns={},
        )

        status_code, removed = self._delete(table)

        assert status_code == status.HTTP_204_NO_CONTENT
        assert removed == []

    def test_shared_upload_is_kept_until_the_last_referencing_table_is_deleted(self) -> None:
        # The same uploaded file can back more than one table. Deleting one table must not pull the
        # file out from under the other — the object is only reclaimed once the last table goes.
        upload_id = "22222222-2222-2222-2222-222222222222"
        url_pattern = f"https://warehouse.posthog.test/file_uploads/team_{self.team.pk}/{upload_id}/orders.csv"
        first = DataWarehouseTable.objects.create(
            team=self.team, name="orders", format="CSVWithNames", url_pattern=url_pattern, columns={}
        )
        second = DataWarehouseTable.objects.create(
            team=self.team, name="orders_copy", format="CSVWithNames", url_pattern=url_pattern, columns={}
        )

        status_code, removed = self._delete(first)
        assert status_code == status.HTTP_204_NO_CONTENT
        assert removed == []

        status_code, removed = self._delete(second)
        assert status_code == status.HTTP_204_NO_CONTENT
        assert removed == [f"test-bucket/file_uploads/team_{self.team.pk}/{upload_id}/orders.csv"]


class TestFileUploadThrottling(SimpleTestCase):
    @parameterized.expand(["upload_file", "create_from_upload", "file"])
    def test_upload_actions_use_the_dedicated_throttle(self, action: str) -> None:
        # The default throttles skip session users, so the heavy upload actions must carry their own
        # per-user/key limit — dropping this reopens the DoS gap.
        viewset = TableViewSet()
        viewset.action = action
        assert {type(t) for t in viewset.get_throttles()} == {FileUploadBurstThrottle, FileUploadSustainedThrottle}

    def test_other_actions_keep_the_default_throttles(self) -> None:
        viewset = TableViewSet()
        viewset.action = "list"
        throttle_types = {type(t) for t in viewset.get_throttles()}
        assert FileUploadBurstThrottle not in throttle_types

    def test_cache_key_is_per_user_not_per_team(self) -> None:
        # Two session members of the same team must land in separate buckets. The inherited
        # team-first key would collide them, letting one member's burst lock out the whole team.
        throttle = FileUploadBurstThrottle()
        with patch("posthog.rate_limit.PersonalAPIKeyAuthentication.find_key_with_source", return_value=None):
            key_a = throttle.get_cache_key(Mock(user=Mock(is_authenticated=True, pk=1)), view=None)
            key_b = throttle.get_cache_key(Mock(user=Mock(is_authenticated=True, pk=2)), view=None)
        assert key_a != key_b
        assert key_a.endswith("1")
        assert key_b.endswith("2")
