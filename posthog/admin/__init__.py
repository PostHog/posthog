# Lazy load admin classes to avoid loading all at startup.
# Admin classes are loaded when Django admin site is first accessed


def register_all_admin():
    from django.contrib import admin

    from posthog.admin.admins import (
        AsyncDeletionAdmin,
        BatchImportAdmin,
        CohortAdmin,
        ColumnConfigurationAdmin,
        DashboardAdmin,
        DashboardTemplateAdmin,
        DataColorThemeAdmin,
        DataDeletionRequestAdmin,
        DataWarehouseTableAdmin,
        DuckgresServerAdmin,
        DuckLakeCatalogAdmin,
        EventIngestionRestrictionConfigAdmin,
        ExperimentAdmin,
        ExperimentSavedMetricAdmin,
        ExternalDataSchemaAdmin,
        FeatureFlagAdmin,
        GroupTypeMappingAdmin,
        HogFlowAdmin,
        HogFunctionAdmin,
        InsightAdmin,
        InstanceSettingAdmin,
        IntegrationAdmin,
        LinkAdmin,
        OAuthApplicationAdmin,
        OrganizationAdmin,
        OrganizationDomainAdmin,
        OrganizationIntegrationAdmin,
        PersonalAPIKeyAdmin,
        PersonDistinctIdAdmin,
        PluginAdmin,
        PluginConfigAdmin,
        ProductTourAdmin,
        ProjectAdmin,
        SurveyAdmin,
        TeamAdmin,
        TextAdmin,
        UserAdmin,
        UserIntegrationAdmin,
        UserProductListAdmin,
    )
    from posthog.admin.admins.exported_asset_admin import ExportedAssetAdmin
    from posthog.models import (
        AsyncDeletion,
        BatchImport,
        Cohort,
        ColumnConfiguration,
        DataColorTheme,
        DataDeletionRequest,
        DataWarehouseTable,
        DuckgresServer,
        DuckLakeCatalog,
        EventIngestionRestrictionConfig,
        ExportedAsset,
        FeatureFlag,
        GroupTypeMapping,
        HogFlow,
        HogFunction,
        Insight,
        InstanceSetting,
        Integration,
        Organization,
        OrganizationDomain,
        OrganizationIntegration,
        PersonalAPIKey,
        PersonDistinctId,
        Plugin,
        PluginConfig,
        Project,
        Team,
        User,
        UserIntegration,
    )
    from posthog.models.file_system.user_product_list import UserProductList
    from posthog.models.oauth import OAuthApplication

    from products.dashboards.backend.models.dashboard import Dashboard
    from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
    from products.dashboards.backend.models.dashboard_tile import Text
    from products.desktop_recordings.backend.admin import DesktopRecordingAdmin
    from products.desktop_recordings.backend.models import DesktopRecording
    from products.endpoints.backend.admin import EndpointAdmin, EndpointVersionAdmin
    from products.endpoints.backend.models import Endpoint, EndpointVersion
    from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric
    from products.legal_documents.backend.admin import LegalDocumentAdmin
    from products.legal_documents.backend.models import LegalDocument
    from products.links.backend.models import Link
    from products.mcp_store.backend.admin import MCPServerTemplateAdmin
    from products.mcp_store.backend.models import MCPServerTemplate
    from products.signals.backend.admin import SignalReportAdmin
    from products.signals.backend.models import SignalReport
    from products.surveys.backend.models import Survey
    from products.tasks.backend.admin import (
        CodeInviteAdmin,
        CodeInviteRedemptionAdmin,
        SandboxSnapshotAdmin,
        TaskAdmin,
        TaskRunAdmin,
    )
    from products.tasks.backend.models import CodeInvite, CodeInviteRedemption, SandboxSnapshot, Task, TaskRun

    admin.site.register(Organization, OrganizationAdmin)
    admin.site.register(OrganizationDomain, OrganizationDomainAdmin)
    admin.site.register(OrganizationIntegration, OrganizationIntegrationAdmin)
    admin.site.register(Project, ProjectAdmin)
    admin.site.register(Team, TeamAdmin)
    admin.site.register(User, UserAdmin)

    admin.site.register(Dashboard, DashboardAdmin)
    admin.site.register(DashboardTemplate, DashboardTemplateAdmin)
    admin.site.register(Insight, InsightAdmin)
    admin.site.register(GroupTypeMapping, GroupTypeMappingAdmin)
    admin.site.register(DataColorTheme, DataColorThemeAdmin)

    admin.site.register(Experiment, ExperimentAdmin)
    admin.site.register(ExperimentSavedMetric, ExperimentSavedMetricAdmin)
    admin.site.register(ExportedAsset, ExportedAssetAdmin)
    admin.site.register(FeatureFlag, FeatureFlagAdmin)

    admin.site.register(AsyncDeletion, AsyncDeletionAdmin)
    admin.site.register(DataDeletionRequest, DataDeletionRequestAdmin)
    admin.site.register(InstanceSetting, InstanceSettingAdmin)
    admin.site.register(Integration, IntegrationAdmin)
    admin.site.register(UserIntegration, UserIntegrationAdmin)
    admin.site.register(PluginConfig, PluginConfigAdmin)
    admin.site.register(Plugin, PluginAdmin)
    admin.site.register(Text, TextAdmin)

    admin.site.register(Cohort, CohortAdmin)
    admin.site.register(ColumnConfiguration, ColumnConfigurationAdmin)
    admin.site.register(PersonDistinctId, PersonDistinctIdAdmin)

    admin.site.register(Survey, SurveyAdmin)

    from products.product_tours.backend.models import ProductTour

    admin.site.register(ProductTour, ProductTourAdmin)

    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

    admin.site.register(ExternalDataSchema, ExternalDataSchemaAdmin)
    admin.site.register(DataWarehouseTable, DataWarehouseTableAdmin)
    admin.site.register(DuckgresServer, DuckgresServerAdmin)
    admin.site.register(DuckLakeCatalog, DuckLakeCatalogAdmin)
    admin.site.register(HogFlow, HogFlowAdmin)
    admin.site.register(HogFunction, HogFunctionAdmin)
    admin.site.register(EventIngestionRestrictionConfig, EventIngestionRestrictionConfigAdmin)
    admin.site.register(LegalDocument, LegalDocumentAdmin)
    admin.site.register(Link, LinkAdmin)
    admin.site.register(BatchImport, BatchImportAdmin)

    admin.site.register(PersonalAPIKey, PersonalAPIKeyAdmin)
    admin.site.register(OAuthApplication, OAuthApplicationAdmin)

    admin.site.register(Task, TaskAdmin)
    admin.site.register(TaskRun, TaskRunAdmin)
    admin.site.register(SandboxSnapshot, SandboxSnapshotAdmin)
    admin.site.register(CodeInvite, CodeInviteAdmin)
    admin.site.register(CodeInviteRedemption, CodeInviteRedemptionAdmin)

    admin.site.register(DesktopRecording, DesktopRecordingAdmin)

    admin.site.register(Endpoint, EndpointAdmin)
    admin.site.register(EndpointVersion, EndpointVersionAdmin)

    admin.site.register(SignalReport, SignalReportAdmin)

    admin.site.register(UserProductList, UserProductListAdmin)

    admin.site.register(MCPServerTemplate, MCPServerTemplateAdmin)


# :KRUDGE: OAuth models live in the `posthog` app, so by default they appear
# under "PostHog" in the admin sidebar alongside dozens of unrelated models.
# The "real" fix would be to move these to `products/oauth/` so Django groups
# them automatically — but every model here is `swappable` (referenced as
# `OAUTH2_PROVIDER_APPLICATION_MODEL` etc.). Changing the app_label means
# rewriting every existing migration that points at the swappable target,
# both in oauth2_provider and in any FK that's been added on top — a known
# Django landmine. Until there's a separate reason to isolate OAuth as its
# own product, override `get_app_list` instead.
_OAUTH_ADMIN_MODEL_NAMES = frozenset(
    {
        "OAuthApplication",
        "OAuthAccessToken",
        "OAuthGrant",
        "OAuthIDToken",
        "OAuthRefreshToken",
    }
)


def install_admin_app_list_overrides():
    """Override admin sidebar grouping. Must run before any admin request so the
    first call goes through the patched function — otherwise the lazy admin
    registry would only install this mid-call after `get_app_list` has already
    started executing on the original method."""
    from django.contrib import admin
    from django.urls import NoReverseMatch, reverse

    original_get_app_list = admin.site.get_app_list

    def _build_oauth_app_dict(oauth_models):
        try:
            app_url = reverse("admin:app_list", kwargs={"app_label": "oauth"})
        except NoReverseMatch:
            app_url = ""
        return {
            "name": "OAuth",
            "app_label": "oauth",
            "app_url": app_url,
            "has_module_perms": True,
            "models": oauth_models,
        }

    def _extract_oauth_models(app_list):
        oauth_models = []
        for app in app_list:
            kept = []
            for model in app["models"]:
                if model.get("object_name") in _OAUTH_ADMIN_MODEL_NAMES:
                    oauth_models.append(model)
                else:
                    kept.append(model)
            app["models"] = kept
        return oauth_models

    def get_app_list(request, app_label=None):
        # The synthetic "oauth" app_label has no real models registered against it,
        # so we have to source its models from the `posthog` app and rebuild the
        # group ourselves — otherwise visiting /admin/oauth/ would 404.
        if app_label == "oauth":
            posthog_app_list = original_get_app_list(request, app_label="posthog")
            oauth_models = _extract_oauth_models(posthog_app_list)
            oauth_models.sort(key=lambda model: model["name"].lower())
            return [_build_oauth_app_dict(oauth_models)] if oauth_models else []

        app_list = original_get_app_list(request, app_label=app_label)
        oauth_models = _extract_oauth_models(app_list)
        if not oauth_models:
            return app_list

        oauth_models.sort(key=lambda model: model["name"].lower())
        app_list = [app for app in app_list if app["models"]]
        app_list.append(_build_oauth_app_dict(oauth_models))
        app_list.sort(key=lambda app: app["name"].lower())
        return app_list

    admin.site.get_app_list = get_app_list  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
