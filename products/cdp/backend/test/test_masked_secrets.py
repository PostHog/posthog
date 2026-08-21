from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from parameterized import parameterized

from posthog.admin import register_all_admin
from posthog.cdp.validation import MASKED_SECRET_VALUE

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.masked_secrets import (
    MaskedSecretFinding,
    _masked_input_keys,
    scan_for_masked_secrets,
    summarize_by_organization,
)

SECRET_SCHEMA = [{"key": "api_key", "type": "string", "secret": True}]

# `posthog/apps.py` installs the lazy admin registry only `if not settings.TEST`, and that wrapper
# is the sole caller of `register_all_admin()` — so under tests nothing registers this admin and
# its custom URLs cannot be reversed.
register_all_admin()


def _finding(*, organization_id, enabled: bool) -> MaskedSecretFinding:
    return MaskedSecretFinding(
        organization_id=organization_id,
        organization_name="Org",
        team_id=1,
        team_name="Team",
        hog_function_id=uuid4(),
        hog_function_name="Destination",
        hog_function_type="destination",
        template_id="template-customerio",
        enabled=enabled,
        deleted=False,
        updated_at=timezone.now(),
        masked_live_inputs=("api_key",),
        masked_draft_inputs=(),
        configuration_url="https://example.com/config",
    )


class TestMaskedInputKeys(SimpleTestCase):
    @parameterized.expand(
        [
            ("mask", {"api_key": {"value": MASKED_SECRET_VALUE}}, ("api_key",)),
            ("real_secret", {"api_key": {"value": "sk-live-abc"}}, ()),
            ("mask_substring", {"api_key": {"value": f"{MASKED_SECRET_VALUE}abc"}}, ()),
            ("no_value_key", {"api_key": {"secret": True}}, ()),
            (
                "several_masked_keys",
                {"token": {"value": MASKED_SECRET_VALUE}, "api_key": {"value": MASKED_SECRET_VALUE}},
                ("api_key", "token"),
            ),
            # A row encrypted under a key we no longer hold reads back as the raw ciphertext
            # string, because the field swallows InvalidToken rather than raising.
            ("undecryptable_ciphertext", "gAAAAABm-not-a-dict", ()),
            ("none", None, ()),
            ("entry_is_not_a_dict", {"api_key": "plain"}, ()),
        ]
    )
    def test_masked_input_keys(self, _name: str, stored: object, expected: tuple[str, ...]) -> None:
        assert _masked_input_keys(stored) == expected


class TestSummarizeByOrganization(SimpleTestCase):
    def test_organizations_with_enabled_functions_sort_first(self) -> None:
        disabled_org, enabled_org = uuid4(), uuid4()
        findings = [
            _finding(organization_id=disabled_org, enabled=False),
            _finding(organization_id=disabled_org, enabled=False),
            _finding(organization_id=enabled_org, enabled=True),
        ]

        summaries = summarize_by_organization(findings)

        assert [summary.organization_id for summary in summaries] == [enabled_org, disabled_org]
        assert summaries[0].enabled_hog_function_count == 1
        assert summaries[1].hog_function_count == 2


class MaskedSecretsDatabaseTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create_hog_function(
        self,
        *,
        secret_value: str | None = MASKED_SECRET_VALUE,
        draft_secret_value: str | None = None,
        deleted: bool = False,
        enabled: bool = True,
    ) -> HogFunction:
        hog_function = HogFunction.objects.create(
            team=self.team,
            name="Send events to a third party",
            type="destination",
            template_id="template-customerio",
            enabled=enabled,
            deleted=deleted,
            hog="return event",
            inputs_schema=SECRET_SCHEMA,
            inputs={"api_key": {"value": secret_value}} if secret_value is not None else {},
        )
        if draft_secret_value is not None:
            hog_function.draft_encrypted_inputs = {"api_key": {"value": draft_secret_value}}
            hog_function.save(update_fields=["draft_encrypted_inputs"])
        return hog_function


class TestScanForMaskedSecrets(MaskedSecretsDatabaseTest):
    def test_reports_masked_live_secret_and_ignores_a_real_one(self) -> None:
        masked = self._create_hog_function(secret_value=MASKED_SECRET_VALUE)
        self._create_hog_function(secret_value="sk-live-abc")

        scan = scan_for_masked_secrets()

        assert [finding.hog_function_id for finding in scan.findings] == [masked.id]
        assert scan.findings[0].masked_live_inputs == ("api_key",)
        assert scan.findings[0].organization_id == self.organization.id
        assert scan.scanned_count == 2

    def test_reports_a_masked_draft_secret_on_a_healthy_function(self) -> None:
        hog_function = self._create_hog_function(secret_value="sk-live-abc", draft_secret_value=MASKED_SECRET_VALUE)

        scan = scan_for_masked_secrets()

        assert [finding.hog_function_id for finding in scan.findings] == [hog_function.id]
        assert scan.findings[0].masked_live_inputs == ()
        assert scan.findings[0].masked_draft_inputs == ("api_key",)

    @parameterized.expand([("excluded_by_default", False, 0), ("included_on_request", True, 1)])
    def test_deleted_hog_functions(self, _name: str, include_deleted: bool, expected_count: int) -> None:
        self._create_hog_function(deleted=True)

        scan = scan_for_masked_secrets(include_deleted=include_deleted)

        assert len(scan.findings) == expected_count

    def test_hitting_the_cap_is_reported_rather_than_silently_truncating(self) -> None:
        self._create_hog_function()
        self._create_hog_function()

        scan = scan_for_masked_secrets(max_results=1)

        assert len(scan.findings) == 1
        assert scan.truncated is True


class TestMaskedSecretsAdmin(MaskedSecretsDatabaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_the_page_renders_the_findings(self) -> None:
        hog_function = self._create_hog_function()

        response = self.client.post(reverse("admin:hog-function-masked-secrets"), {"max_results": 100, "_scan": "Scan"})

        assert response.status_code == 200
        assert str(hog_function.id) in response.content.decode()

    def test_the_page_downloads_the_findings_as_csv(self) -> None:
        hog_function = self._create_hog_function()

        response = self.client.post(
            reverse("admin:hog-function-masked-secrets"), {"max_results": 100, "_csv": "Download CSV"}
        )

        assert response["Content-Type"] == "text/csv"
        body = response.content.decode()
        assert str(hog_function.id) in body
        # The scan reports which inputs are masked, never what is stored in them.
        assert MASKED_SECRET_VALUE not in body

    def test_a_capped_scan_does_not_hand_back_a_partial_csv(self) -> None:
        self._create_hog_function()
        self._create_hog_function()

        response = self.client.post(
            reverse("admin:hog-function-masked-secrets"), {"max_results": 1, "_csv": "Download CSV"}
        )

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")
