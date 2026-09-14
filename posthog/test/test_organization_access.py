from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.organization_access import (
    EXTRA_ALLOWED_PAGES,
    ORG_INDEPENDENT_PAGES,
    OrganizationBlock,
    organization_block,
    page_is_allowed,
)


class TestOrganizationBlock(SimpleTestCase):
    @parameterized.expand(
        [
            ("active", True, False, None),
            ("never_deactivated", None, False, None),
            ("deactivated", False, False, OrganizationBlock.DEACTIVATED),
            ("pending_deletion", True, True, OrganizationBlock.PENDING_DELETION),
            ("deletion_outranks_deactivation", False, True, OrganizationBlock.PENDING_DELETION),
        ]
    )
    def test_block_state(self, _name, is_active, is_pending_deletion, expected) -> None:
        organization = Organization(is_active=is_active, is_pending_deletion=is_pending_deletion)
        self.assertEqual(organization_block(organization), expected)


class TestPageIsAllowed(SimpleTestCase):
    @parameterized.expand(
        [
            ("deactivated_keeps_its_own_page", OrganizationBlock.DEACTIVATED, "/organization-deactivated", True),
            ("deactivated_keeps_billing", OrganizationBlock.DEACTIVATED, "/organization/billing", True),
            (
                "deactivated_keeps_billing_section",
                OrganizationBlock.DEACTIVATED,
                "/organization/billing/overview",
                True,
            ),
            (
                "deactivated_keeps_invites",
                OrganizationBlock.DEACTIVATED,
                "/signup/0190a1b2-c3d4-0000-0000-000000000001",
                True,
            ),
            ("deactivated_drops_the_app", OrganizationBlock.DEACTIVATED, "/dashboard", False),
            (
                "pending_deletion_keeps_its_own_page",
                OrganizationBlock.PENDING_DELETION,
                "/organization-pending-deletion",
                True,
            ),
            ("pending_deletion_drops_billing", OrganizationBlock.PENDING_DELETION, "/organization/billing", False),
            (
                "pending_deletion_keeps_invites",
                OrganizationBlock.PENDING_DELETION,
                "/signup/0190a1b2-c3d4-0000-0000-000000000001",
                True,
            ),
            (
                "pending_deletion_drops_the_other_block_page",
                OrganizationBlock.PENDING_DELETION,
                "/organization-deactivated",
                False,
            ),
        ]
    )
    def test_page_access(self, _name, block, path, expected) -> None:
        self.assertEqual(page_is_allowed(block, path), expected)

    def test_every_block_declares_its_extra_pages(self) -> None:
        # A missing entry raises a KeyError on the first blocked request, not at import time.
        self.assertEqual(set(EXTRA_ALLOWED_PAGES), set(OrganizationBlock))

    def test_org_independent_pages_are_prefixes(self) -> None:
        # `page_is_allowed` matches with `startswith`, so a missing trailing slash would admit
        # every path beginning with the same characters.
        for page in ORG_INDEPENDENT_PAGES:
            self.assertTrue(page.startswith("/"), page)
            self.assertTrue(page.endswith("/"), page)
