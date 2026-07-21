import io

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

VIEW_MODULE = "products.data_warehouse.backend.presentation.views.external_data_source"


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
class TestExternalDataSourceUploadFile(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/environments/{self.team.pk}/external_data_sources/upload_file/"
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
            ("unsupported_format", "xlsx", "Invalid format"),
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


SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source"


@override_settings(DATAWAREHOUSE_BUCKET="test-bucket")
class TestFileUploadSourceCreation(APIBaseTest):
    def test_an_uploaded_file_becomes_a_managed_source(self) -> None:
        # Guards the two-step contract the wizard depends on: the upload endpoint's `upload_id` has
        # to be accepted by the JSON create endpoint, and `get_schemas` has to agree with the
        # `schemas` the client sends, or create rejects with "Schemas not given".
        s3 = _FakeS3()
        with patch(f"{VIEW_MODULE}.get_s3_client", return_value=s3):
            upload = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/upload_file/",
                {"file": SimpleUploadedFile("orders.csv", b"id,total\n1,9\n"), "file_format": "csv"},
                format="multipart",
            )
        assert upload.status_code == status.HTTP_201_CREATED, upload.json()
        upload_id = upload.json()["upload_id"]

        existing_s3 = _FakeS3(exists_result=True)
        with patch(f"{SOURCE_MODULE}.get_s3_client", return_value=existing_s3):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "FileUpload",
                    "created_via": "web",
                    "payload": {
                        "table_name": "orders",
                        "file_format": "csv",
                        "upload_id": upload_id,
                        "filename": "orders.csv",
                        "schemas": [{"name": "orders", "should_sync": True, "sync_type": "full_refresh"}],
                    },
                },
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        source = ExternalDataSource.objects.get(id=response.json()["id"])
        assert source.source_type == "FileUpload"
        assert source.job_inputs["upload_id"] == upload_id
        assert source.job_inputs["filename"] == "orders.csv"
        assert [s.name for s in source.schemas.all()] == ["orders"]
