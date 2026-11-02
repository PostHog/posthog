import type { Describer } from 'lib/components/ActivityLog/humanizeActivity'

import { productActivityDescribers } from '~/productActivityDescribers'
import { ActivityScope } from '~/types'

export type ActivityDescriberLoader = () => Promise<Describer>

// Scopes that no product owns. A product registers its describers in its own manifest instead.
const coreActivityDescribers: Partial<Record<ActivityScope, ActivityDescriberLoader>> = {
    [ActivityScope.BILLING]: () =>
        import('scenes/billing/activityDescriptions').then((m) => m.billingActivityDescriber),
    [ActivityScope.INSTANCE_SETTING]: () =>
        import('./activityDescriptions/instanceSettingActivityDescriber').then(
            (m) => m.instanceSettingActivityDescriber
        ),
    [ActivityScope.OAUTH_APPLICATION]: () =>
        import('scenes/settings/user/activityDescriptions').then((m) => m.oauthApplicationActivityDescriber),
    [ActivityScope.ORGANIZATION]: () =>
        import('scenes/settings/organization/activityDescriptions').then((m) => m.organizationActivityDescriber),
    [ActivityScope.ORGANIZATION_DOMAIN]: () =>
        import('scenes/settings/organization/activityDescriptions').then((m) => m.organizationDomainActivityDescriber),
    [ActivityScope.ORGANIZATION_INVITE]: () =>
        import('scenes/settings/organization/activityDescriptions').then((m) => m.organizationActivityDescriber),
    [ActivityScope.ORGANIZATION_MEMBERSHIP]: () =>
        import('scenes/settings/organization/activityDescriptions').then((m) => m.organizationActivityDescriber),
    [ActivityScope.PERSONAL_API_KEY]: () =>
        import('scenes/settings/user/activityDescriptions').then((m) => m.personalAPIKeyActivityDescriber),
    [ActivityScope.PROJECT_SECRET_API_KEY]: () =>
        import('scenes/settings/project/activityDescriptions').then((m) => m.projectSecretAPIKeyActivityDescriber),
    [ActivityScope.TAG]: () =>
        import('./activityDescriptions/tagActivityDescriber').then((m) => m.tagActivityDescriber),
    [ActivityScope.TAGGED_ITEM]: () =>
        import('./activityDescriptions/tagActivityDescriber').then((m) => m.tagActivityDescriber),
    [ActivityScope.TEAM]: () =>
        import('scenes/team-activity/teamActivityDescriber').then((m) => m.teamActivityDescriber),
    [ActivityScope.USER]: () =>
        import('scenes/authentication/shared/activityDescriptions').then((m) => m.userActivityDescriber),
}

export const activityDescriberLoaders: Partial<Record<ActivityScope, ActivityDescriberLoader>> = {
    ...coreActivityDescribers,
    ...productActivityDescribers,
}
