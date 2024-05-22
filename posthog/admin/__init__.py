from django.contrib import admin

from posthog.admin.admins import (
    AsyncDeletionAdmin,
    CohortAdmin,
    DashboardAdmin,
    DataWarehouseTableAdmin,
    ExperimentAdmin,
    FeatureFlagAdmin,
    InsightAdmin,
    InstanceSettingAdmin,
    OrganizationAdmin,
    PersonAdmin,
    PersonDistinctIdAdmin,
    PluginAdmin,
    PluginConfigAdmin,
    ProjectAdmin,
    RedisMutationAdmin,
    SurveyAdmin,
    TeamAdmin,
    TextAdmin,
    UserAdmin,
)
from posthog.models import (
    AsyncDeletion,
    Cohort,
    Dashboard,
    DataWarehouseTable,
    Experiment,
    FeatureFlag,
    Insight,
    InstanceSetting,
    Organization,
    Person,
    PersonDistinctId,
    Plugin,
    PluginConfig,
    Project,
    RedisMutation,
    Survey,
    Team,
    Text,
    User,
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

admin.site.register(RedisMutation, RedisMutationAdmin)
