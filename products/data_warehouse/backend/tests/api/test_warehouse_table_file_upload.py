import io

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

import pandas as pd
from parameterized import parameterized
from rest_framework import status

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
        self._exists_result = exists_result

    def open(self, path: str, mode: str) -> io.BytesIO:
        return _CapturingBuffer(self.written, path)

    def exists(self, path: str) -> bool:
        return self._exists_result


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
