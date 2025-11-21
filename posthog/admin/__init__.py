# Lazy load admin classes to avoid loading all at startup.
# Admin classes are loaded when Django admin site is first accessed


def register_all_admin():
    from django.contrib import admin

    from posthog.admin.admins import (
        AsyncDeletionAdmin,
        BatchImportAdmin,
        CohortAdmin,
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
        ProjectAdmin,
        SurveyAdmin,
        TeamAdmin,
        TextAdmin,
        UserAdmin,
    )
    from posthog.models.async_deletion.async_deletion import AsyncDeletion
    from posthog.models.batch_imports import BatchImport
    from posthog.models.cohort.cohort import Cohort
    from posthog.models.dashboard import Dashboard
    from posthog.models.dashboard_templates import DashboardTemplate
    from posthog.models.dashboard_tile import Text
    from posthog.models.data_color_theme import DataColorTheme
    from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig
    from posthog.models.experiment import Experiment, ExperimentSavedMetric
    from posthog.models.feature_flag.feature_flag import FeatureFlag
    from posthog.models.group_type_mapping import GroupTypeMapping
    from posthog.models.hog_functions.hog_function import HogFunction
    from posthog.models.insight import Insight
    from posthog.models.instance_setting import InstanceSetting
    from posthog.models.link import Link
    from posthog.models.oauth import OAuthApplication
    from posthog.models.organization import Organization
    from posthog.models.organization_domain import OrganizationDomain
    from posthog.models.person.person import PersonDistinctId
    from posthog.models.personal_api_key import PersonalAPIKey
    from posthog.models.plugin import Plugin, PluginConfig
    from posthog.models.project import Project
    from posthog.models.surveys.survey import Survey
    from posthog.models.team.team import Team
    from posthog.models.user import User

    from products.data_warehouse.backend.models.table import DataWarehouseTable
    from products.desktop_recordings.backend.admin import DesktopRecordingAdmin
    from products.desktop_recordings.backend.models import DesktopRecording
    from products.tasks.backend.admin import SandboxSnapshotAdmin
    from products.tasks.backend.models import SandboxSnapshot

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
    admin.site.register(PersonDistinctId, PersonDistinctIdAdmin)

    admin.site.register(Survey, SurveyAdmin)

    admin.site.register(DataWarehouseTable, DataWarehouseTableAdmin)
    admin.site.register(HogFunction, HogFunctionAdmin)
    admin.site.register(EventIngestionRestrictionConfig, EventIngestionRestrictionConfigAdmin)
    admin.site.register(Link, LinkAdmin)
    admin.site.register(BatchImport, BatchImportAdmin)

    admin.site.register(PersonalAPIKey, PersonalAPIKeyAdmin)
    # Register OAuthApplication with our custom admin
    # If oauth2_provider already registered it, unregister it first
    try:
        admin.site.unregister(OAuthApplication)
    except Exception:
        pass  # Model might not be registered yet
    admin.site.register(OAuthApplication, OAuthApplicationAdmin)

    admin.site.register(SandboxSnapshot, SandboxSnapshotAdmin)
    admin.site.register(DesktopRecording, DesktopRecordingAdmin)
