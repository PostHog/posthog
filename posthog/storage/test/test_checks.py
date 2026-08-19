from django.test import SimpleTestCase

from posthog.storage.checks import check_object_storage_config


class TestObjectStorageConfigCheck(SimpleTestCase):
    def test_no_error_for_valid_config(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000",
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://public.example.com",
            OBJECT_STORAGE_BUCKET="posthog",
        ):
            assert check_object_storage_config(None) == []

    def test_error_for_unsubstituted_public_endpoint(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000",
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://${POSTHOG_DOMAIN}",
            OBJECT_STORAGE_BUCKET="posthog",
        ):
            errors = check_object_storage_config(None)

        assert [error.id for error in errors] == ["posthog.E004"]

    def test_error_for_endpoint_botocore_rejects(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_ENDPOINT="http://posthog_objectstorage:19000",
            OBJECT_STORAGE_PUBLIC_ENDPOINT="http://posthog_objectstorage:19000",
            OBJECT_STORAGE_BUCKET="posthog",
        ):
            errors = check_object_storage_config(None)

        assert [error.id for error in errors] == ["posthog.E005", "posthog.E004"]

    def test_error_for_unsubstituted_bucket(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000",
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://public.example.com",
            OBJECT_STORAGE_BUCKET="@@RECORDINGS_BUCKET@@",
        ):
            errors = check_object_storage_config(None)

        assert [error.id for error in errors] == ["posthog.E006"]

    def test_no_error_when_storage_disabled(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=False,
            OBJECT_STORAGE_ENDPOINT="http://posthog_objectstorage:19000",
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://${POSTHOG_DOMAIN}",
            OBJECT_STORAGE_BUCKET="@@RECORDINGS_BUCKET@@",
        ):
            assert check_object_storage_config(None) == []
