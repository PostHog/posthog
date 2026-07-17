import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from posthog.admin import _OAUTH_ADMIN_MODEL_NAMES, install_admin_app_list_overrides, register_all_admin
from posthog.admin.admins.event_ingestion_restriction_config import EventIngestionRestrictionConfigAdmin
from posthog.admin.admins.user_admin import UserAdmin, UserChangeForm
from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline, OrganizationMemberInline
from posthog.models import User
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig

from products.alerts.backend.models.alert import AlertConfiguration
from products.cdp.backend.admin.plugin_attachment_inline import PluginAttachmentInline
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.plugin import Plugin, PluginConfig
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import Text
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric
from products.product_analytics.backend.models.insight import Insight
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob


class TestOAuthSidebarRegrouping(BaseTest):
    def _patched_get_app_list(self):
        site = AdminSite()
        site.get_app_list = lambda request, app_label=None: [  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            {
                "name": "PostHog",
                "app_label": "posthog",
                "app_url": "/admin/posthog/",
                "has_module_perms": True,
                "models": [
                    {"name": "OAuth applications", "object_name": "OAuthApplication"},
                    {"name": "OAuth access tokens", "object_name": "OAuthAccessToken"},
                    {"name": "OAuth grants", "object_name": "OAuthGrant"},
                    {"name": "OAuth ID tokens", "object_name": "OAuthIDToken"},
                    {"name": "OAuth refresh tokens", "object_name": "OAuthRefreshToken"},
                    {"name": "Users", "object_name": "User"},
                ]
                if app_label in (None, "posthog")
                else [],
            }
        ]
        with patch.object(admin, "site", site):
            install_admin_app_list_overrides()
            return site.get_app_list

    def test_oauth_models_moved_to_oauth_section(self):
        get_app_list = self._patched_get_app_list()
        result = get_app_list(request=None)

        oauth_apps = [app for app in result if app["app_label"] == "oauth"]
        assert len(oauth_apps) == 1
        oauth_object_names = {model["object_name"] for model in oauth_apps[0]["models"]}
        assert oauth_object_names == _OAUTH_ADMIN_MODEL_NAMES

        posthog_apps = [app for app in result if app["app_label"] == "posthog"]
        assert len(posthog_apps) == 1
        posthog_object_names = {model["object_name"] for model in posthog_apps[0]["models"]}
        assert posthog_object_names == {"User"}

    def test_oauth_app_label_returns_only_oauth_models(self):
        get_app_list = self._patched_get_app_list()
        result = get_app_list(request=None, app_label="oauth")

        assert len(result) == 1
        assert result[0]["app_label"] == "oauth"
        assert result[0]["name"] == "OAuth"
        assert {model["object_name"] for model in result[0]["models"]} == _OAUTH_ADMIN_MODEL_NAMES


class TestUserAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user_admin = UserAdmin(User, AdminSite())
        self.request_factory = RequestFactory()

    def search_user_ids(self, search_term: str) -> list[int]:
        request = self.request_factory.get("/admin/posthog/user/", {"q": search_term})
        queryset, _use_distinct = self.user_admin.get_search_results(request, User.objects.all(), search_term)
        return list(queryset.values_list("id", flat=True))

    def test_search_by_distinct_id_returns_matching_user(self) -> None:
        matching_user = User.objects.create_user(
            email="distinct-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="billing-distinct-id",
        )
        User.objects.create_user(
            email="other-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="other-distinct-id",
        )

        assert self.search_user_ids("billing-distinct-id") == [matching_user.id]

    def test_search_by_email_still_returns_matching_user(self) -> None:
        matching_user = User.objects.create_user(
            email="email-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="email-search-distinct-id",
        )

        assert self.search_user_ids("email-admin-search@example.com") == [matching_user.id]

    def test_non_matching_distinct_id_returns_no_users(self) -> None:
        User.objects.create_user(
            email="nonmatch-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="known-distinct-id",
        )

        assert self.search_user_ids("missing-distinct-id") == []

    def test_clean_passkeys_enabled_for_2fa_rejects_when_user_has_no_verified_passkey(self) -> None:
        from django.core.exceptions import ValidationError

        form = UserChangeForm(instance=self.user)
        form.cleaned_data = {"passkeys_enabled_for_2fa": True}
        with self.assertRaises(ValidationError):
            form.clean_passkeys_enabled_for_2fa()


class TestPluginAttachmentInline(BaseTest):
    def test_parsed_json_escapes_html_in_values(self):
        inline = PluginAttachmentInline(MagicMock(), MagicMock())
        attachment = MagicMock()
        attachment.file_size = 100
        attachment.contents = b'{"xss": "</pre><script>alert(1)</script><pre>"}'

        result = str(inline.parsed_json(attachment))

        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_parsed_json_error_escapes_html(self):
        inline = PluginAttachmentInline(MagicMock(), MagicMock())
        attachment = MagicMock()
        attachment.file_size = 100
        attachment.contents = b"not json"

        result = str(inline.parsed_json(attachment))

        assert "cannot preview:" in result

    def test_raw_contents_error_escapes_html(self):
        inline = PluginAttachmentInline(MagicMock(), MagicMock())
        attachment = MagicMock()
        attachment.file_size = 2 * 1024 * 1024

        result = str(inline.raw_contents(attachment))

        assert "cannot preview:" in result


class TestEventIngestionRestrictionConfigAdmin:
    def test_display_team_id_reads_annotation(self):
        admin_instance = EventIngestionRestrictionConfigAdmin(EventIngestionRestrictionConfig, AdminSite())
        cases = [
            ("present", 42, 42),
            ("missing", None, None),
        ]
        for label, annotation_value, expected in cases:
            obj = MagicMock()
            obj.team_id_from_token = annotation_value
            assert admin_instance.display_team_id(obj) == expected, label


class TestEventIngestionRestrictionConfigAdminConfig:
    def test_display_team_id_in_list_display_and_readonly_fields(self):
        admin_instance = EventIngestionRestrictionConfigAdmin(EventIngestionRestrictionConfig, AdminSite())
        assert "display_team_id" in admin_instance.list_display
        assert "display_team_id" in admin_instance.readonly_fields


class TestProductAdminRegistration:
    # Regression guard: these models' admin classes live in their product app
    # (`products/<name>/backend/admin.py` or an `admin/` package), not in the
    # central `posthog/admin/admins/` registry. They register only because
    # `autodiscover_modules("admin")` imports each app's `admin` module — and for
    # the `admin/` package layout, only the package's `__init__`, so that
    # `__init__` must in turn import every submodule for the `@admin.register`
    # decorators to fire. Miss either and the model silently vanishes from admin.
    @pytest.mark.parametrize(
        "model",
        [
            HogFlow,
            HogFlowTemplate,
            HogFlowBatchJob,
            HogFunction,
            Plugin,
            PluginConfig,
            AlertConfiguration,
            Dashboard,
            DashboardTemplate,
            Text,
            DataWarehouseTable,
            ExternalDataSchema,
            Experiment,
            ExperimentSavedMetric,
            Insight,
            ProductTour,
            Survey,
        ],
        ids=lambda m: m.__name__,
    )
    def test_moved_product_models_are_registered(self, model):
        # Tests skip the lazy admin registry, so trigger registration explicitly.
        register_all_admin()
        assert admin.site.is_registered(model), f"{model.__name__} is not registered in Django admin"


class TestOrganizationMemberInlineConfig(BaseTest):
    def test_invited_by_is_readonly_and_never_rendered_as_user_select(self):
        # Regression guard: invited_by must not become an editable FK select in admin inlines.
        assert "invited_by" in OrganizationMemberInline.fields
        assert "invited_by" in OrganizationMemberInline.readonly_fields
        assert "invited_by" in OrganizationMemberForUserInline.fields
        assert "invited_by" in OrganizationMemberForUserInline.readonly_fields
