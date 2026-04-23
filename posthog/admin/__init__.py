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
    from products.mcp_store.backend.admin import MCPServerAdmin, MCPServerTemplateAdmin
    from products.mcp_store.backend.models import MCPServer, MCPServerTemplate
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

    admin.site.register(MCPServer, MCPServerAdmin)
    admin.site.register(MCPServerTemplate, MCPServerTemplateAdmin)
