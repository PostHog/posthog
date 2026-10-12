from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from ee.billing.salesforce_enrichment.org_regions import fetch_org_regions

EU_ORG = "00000000-0000-4000-8000-000000000001"
US_ORG = "00000000-0000-4000-8000-000000000002"
OTHER_LICENSE_ORG = "00000000-0000-4000-8000-000000000003"
NO_LICENSE_ORG = "00000000-0000-4000-8000-000000000004"
CONFLICT_ORG = "00000000-0000-4000-8000-000000000005"
PARTLY_UNKNOWN_ORG = "00000000-0000-4000-8000-000000000006"


class TestFetchOrgRegions(SimpleTestCase):
    @patch("ee.billing.salesforce_enrichment.org_regions.duckgres_cursor")
    def test_maps_licenses_to_regions_and_never_defaults(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"organization_id": EU_ORG, "license_id": 1},
            {"organization_id": US_ORG, "license_id": 2},
            {"organization_id": OTHER_LICENSE_ORG, "license_id": 3},
            {"organization_id": NO_LICENSE_ORG, "license_id": None},
            {"organization_id": CONFLICT_ORG, "license_id": 1},
            {"organization_id": CONFLICT_ORG, "license_id": 2},
            {"organization_id": PARTLY_UNKNOWN_ORG, "license_id": 2},
            {"organization_id": PARTLY_UNKNOWN_ORG, "license_id": 3},
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        regions = fetch_org_regions(
            [
                f" {EU_ORG.upper()} ",
                US_ORG,
                OTHER_LICENSE_ORG,
                NO_LICENSE_ORG,
                CONFLICT_ORG,
                PARTLY_UNKNOWN_ORG,
                "00000000-0000-4000-8000-000000000007",
                "not-a-uuid",
            ]
        )

        assert regions == {EU_ORG: "EU", US_ORG: "US"}
