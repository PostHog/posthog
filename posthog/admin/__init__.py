from django.contrib import admin

from posthog.admin.admins import (
    OrganizationAdmin,
    UserAdmin,
    TeamAdmin,
    DashboardAdmin,
    InsightAdmin,
    ExperimentAdmin,
    FeatureFlagAdmin,
    AsyncDeletionAdmin,
    InstanceSettingAdmin,
    PluginConfigAdmin,
    PluginAdmin,
    TextAdmin,
    CohortAdmin,
    PersonAdmin,
    PersonDistinctIdAdmin,
    SurveyAdmin,
    DataWarehouseTableAdmin,
    ProjectAdmin,
    HogFunctionAdmin,
)
from posthog.models import (
    Organization,
    User,
    Team,
    Dashboard,
    Insight,
    Experiment,
    FeatureFlag,
    AsyncDeletion,
    InstanceSetting,
    PluginConfig,
    Plugin,
    Text,
    Project,
    Cohort,
    Person,
    PersonDistinctId,
    Survey,
    DataWarehouseTable,
    HogFunction,
)

admin.site.register(Organization, OrganizationAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(User, UserAdmin)

admin.site.register(Dashboard, DashboardAdmin)
admin.site.register(Insight, InsightAdmin)

admin.site.register(Experiment, ExperimentAdmin)
admin.site.register(FeatureFlag, FeatureFlagAdmin)

admin.site.register(AsyncDeletion, AsyncDeletionAdmin)
admin.site.register(InstanceSetting, InstanceSettingAdmin)
admin.site.register(PluginConfig, PluginConfigAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Text, TextAdmin)

admin.site.register(Cohort, CohortAdmin)
admin.site.register(Person, PersonAdmin)
admin.site.register(PersonDistinctId, PersonDistinctIdAdmin)

admin.site.register(Survey, SurveyAdmin)

admin.site.register(DataWarehouseTable, DataWarehouseTableAdmin)
admin.site.register(HogFunction, HogFunctionAdmin)
