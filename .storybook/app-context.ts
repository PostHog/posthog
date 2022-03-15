import { OrganizationMembershipLevel } from 'lib/constants'
import { AppContext } from '~/types'

export const storybookAppContext: AppContext = {
    // @ts-ignore
    current_team: {
        effective_membership_level: OrganizationMembershipLevel.Owner,
        completed_snippet_onboarding: true,
        id: 1,
    },
    current_user: {
        // @ts-ignore
        organization: {
            membership_level: OrganizationMembershipLevel.Owner,
            available_features: [],
        },
    },
    preflight: {
        // @ts-ignore
        instance_preferences: { disable_paid_fs: false },
    },
    default_event_name: '$pageview',
    persisted_feature_flags: [],
}
