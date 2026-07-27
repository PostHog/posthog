from django.test import SimpleTestCase

from posthog.storage.checks import check_object_storage_public_endpoint


class TestObjectStoragePublicEndpointCheck(SimpleTestCase):
    def test_no_error_for_valid_endpoint(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://public.example.com",
        ):
            assert check_object_storage_public_endpoint(None) == []

    def test_error_for_unsubstituted_placeholder(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://${POSTHOG_DOMAIN}",
        ):
            errors = check_object_storage_public_endpoint(None)

        assert len(errors) == 1
        assert errors[0].id == "posthog.E004"

    def test_no_error_when_storage_disabled(self) -> None:
        with self.settings(
            OBJECT_STORAGE_ENABLED=False,
            OBJECT_STORAGE_PUBLIC_ENDPOINT="https://${POSTHOG_DOMAIN}",
        ):
            assert check_object_storage_public_endpoint(None) == []
