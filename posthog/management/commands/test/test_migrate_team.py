from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.migrate_team import REGION_URLS

from products.batch_exports.backend.temporal.destinations.constants import ALLOWED_HTTP_BATCH_EXPORT_URLS


class TestMigrateTeamRegionURLs(SimpleTestCase):
    @parameterized.expand(sorted(REGION_URLS.items()))
    def test_region_url_is_allowlisted(self, region: str, url: str) -> None:
        # The command builds the destination through the ORM, so it skips the API validation. If a
        # region URL drifts off the allowlist, every migration run fails with InvalidDestinationURLError.
        assert url in ALLOWED_HTTP_BATCH_EXPORT_URLS
