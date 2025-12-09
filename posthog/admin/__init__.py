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
        DataWarehouseTableAdmin,
        EventIngestionRestrictionConfigAdmin,
        ExperimentAdmin,
        ExperimentSavedMetricAdmin,
        FeatureFlagAdmin,
        GroupTypeMappingAdmin,
        HogFunctionAdmin,
        InsightAdmin,
        InstanceSettingAdmin,
        LinkAdmin,
        OAuthApplicationAdmin,
        OrganizationAdmin,
        OrganizationDomainAdmin,
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
    from posthog.models import (
        AsyncDeletion,
        BatchImport,
        Cohort,
        ColumnConfiguration,
        Dashboard,
        DashboardTemplate,
        DataColorTheme,
        DataWarehouseTable,
        EventIngestionRestrictionConfig,
        Experiment,
        ExperimentSavedMetric,
        FeatureFlag,
        GroupTypeMapping,
        HogFunction,
        Insight,
        InstanceSetting,
        Link,
        Organization,
        OrganizationDomain,
        PersonalAPIKey,
        PersonDistinctId,
        Plugin,
        PluginConfig,
        Project,
        Survey,
        Team,
        Text,
        User,
    )
    from posthog.models.file_system.user_product_list import UserProductList
    from posthog.models.oauth import OAuthApplication

    from products.desktop_recordings.backend.admin import DesktopRecordingAdmin
    from products.desktop_recordings.backend.models import DesktopRecording
    from products.tasks.backend.admin import SandboxSnapshotAdmin, TaskAdmin, TaskRunAdmin
    from products.tasks.backend.models import SandboxSnapshot, Task, TaskRun

    admin.site.register(Organization, OrganizationAdmin)
    admin.site.register(OrganizationDomain, OrganizationDomainAdmin)
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
    admin.site.register(FeatureFlag, FeatureFlagAdmin)

    admin.site.register(AsyncDeletion, AsyncDeletionAdmin)
    admin.site.register(InstanceSetting, InstanceSettingAdmin)
    admin.site.register(PluginConfig, PluginConfigAdmin)
    admin.site.register(Plugin, PluginAdmin)
    admin.site.register(Text, TextAdmin)

    admin.site.register(Cohort, CohortAdmin)
    admin.site.register(ColumnConfiguration, ColumnConfigurationAdmin)
    admin.site.register(PersonDistinctId, PersonDistinctIdAdmin)

    admin.site.register(Survey, SurveyAdmin)

    from products.product_tours.backend.models import ProductTour

    admin.site.register(ProductTour, ProductTourAdmin)

    admin.site.register(DataWarehouseTable, DataWarehouseTableAdmin)
    admin.site.register(HogFunction, HogFunctionAdmin)
    admin.site.register(EventIngestionRestrictionConfig, EventIngestionRestrictionConfigAdmin)
    admin.site.register(Link, LinkAdmin)
    admin.site.register(BatchImport, BatchImportAdmin)

    admin.site.register(PersonalAPIKey, PersonalAPIKeyAdmin)
    admin.site.register(OAuthApplication, OAuthApplicationAdmin)

    admin.site.register(Task, TaskAdmin)
    admin.site.register(TaskRun, TaskRunAdmin)
    admin.site.register(SandboxSnapshot, SandboxSnapshotAdmin)

    admin.site.register(DesktopRecording, DesktopRecordingAdmin)

    admin.site.register(UserProductList, UserProductListAdmin)
