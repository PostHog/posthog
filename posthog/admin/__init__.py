from django.contrib import admin
from posthog.admin.admins.async_deletion_admin import AsyncDeletionAdmin
from posthog.admin.admins.cohort_admin import CohortAdmin
from posthog.admin.admins.dashboard_admin import DashboardAdmin
from posthog.admin.admins.data_warehouse_table_admin import DataWarehouseTableAdmin
from posthog.admin.admins.experiment_admin import ExperimentAdmin
from posthog.admin.admins.feature_flag_admin import FeatureFlagAdmin
from posthog.admin.admins.insight_admin import InsightAdmin
from posthog.admin.admins.instance_setting_admin import InstanceSettingAdmin
from posthog.admin.admins.organization_admin import OrganizationAdmin
from posthog.admin.admins.person_admin import PersonAdmin
from posthog.admin.admins.person_distinct_id_admin import PersonDistinctIdAdmin
from posthog.admin.admins.plugin_admin import PluginAdmin
from posthog.admin.admins.plugin_config_admin import PluginConfigAdmin
from posthog.admin.admins.survey_admin import SurveyAdmin
from posthog.admin.admins.team_admin import TeamAdmin
from posthog.admin.admins.text_admin import TextAdmin
from posthog.admin.admins.user_admin import UserAdmin

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
    Survey,
    Team,
    Text,
    User,
)

admin.site.register(Organization, OrganizationAdmin)
admin.site.register(User, UserAdmin)
admin.site.register(Team, TeamAdmin)

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
