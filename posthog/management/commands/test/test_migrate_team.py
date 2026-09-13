from posthog.management.commands.migrate_team import REGION_URLS

from products.batch_exports.backend.temporal.destinations.constants import HTTP_ALLOWED_DESTINATION_URLS


def test_region_urls_are_allowed_http_destinations():
    assert set(REGION_URLS.values()) <= HTTP_ALLOWED_DESTINATION_URLS
