from typing import Any

from posthog.test.base import TestMigrations

LEGACY_URL = "https://legacy.example.com/.well-known/oauth-client-metadata"
MOVED_URL = "https://moved.example.com/.well-known/oauth-client-metadata"
STRAY_URL = "https://stray.example.com/.well-known/oauth-client-metadata"


class BackfillCimdClientIdMigrationTest(TestMigrations):
    migrate_from = "1323_proxyrecord_root_redirect_url"
    migrate_to = "1324_backfill_cimd_client_id"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        OAuthApplication = apps.get_model("posthog", "OAuthApplication")
        self.OAuthApplication = OAuthApplication

        def create(client_id: str, **kwargs: Any) -> Any:
            return OAuthApplication.objects.create(
                name=client_id,
                client_id=client_id,
                client_secret="",
                client_type="public",
                authorization_grant_type="authorization-code",
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
                **kwargs,
            )

        self.legacy_cimd = create("generated-legacy", is_cimd_client=True, cimd_metadata_url=LEGACY_URL)
        # Registered by the code that already writes the URL into client_id.
        self.already_moved = create(MOVED_URL, is_cimd_client=True, cimd_metadata_url=MOVED_URL)
        # A stray URL on a non-CIMD row must not become its client_id: the app authenticates
        # under the opaque id an admin gave it.
        self.non_cimd = create("opaque-admin-registered", is_cimd_client=False, cimd_metadata_url=STRAY_URL)

    def test_only_cimd_apps_take_their_metadata_url_as_client_id(self) -> None:
        assert self.OAuthApplication.objects.get(pk=self.legacy_cimd.pk).client_id == LEGACY_URL
        assert self.OAuthApplication.objects.get(pk=self.already_moved.pk).client_id == MOVED_URL
        assert self.OAuthApplication.objects.get(pk=self.non_cimd.pk).client_id == "opaque-admin-registered"
