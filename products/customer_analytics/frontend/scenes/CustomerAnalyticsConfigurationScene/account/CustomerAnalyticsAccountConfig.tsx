import { useActions, useValues } from 'kea'

import { LemonDivider, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter, wordPluralize } from 'lib/utils/strings'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { CustomerAnalyticsConfig } from '~/queries/schema/schema-general'

import { CustomPropertiesConfig } from './CustomPropertiesConfig'
import { RelationshipsConfig } from './RelationshipsConfig'

const NO_ACCOUNT_GROUP = -1

export function CustomerAnalyticsAccountConfig(): JSX.Element {
    const { customerAnalyticsConfig, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { groupTypes } = useValues(groupsModel)
    const { shouldShowGroupsIntroduction } = useValues(groupsAccessLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (shouldShowGroupsIntroduction) {
        return <GroupsIntroduction />
    }

    const options = [
        { value: NO_ACCOUNT_GROUP, label: 'Not configured' },
        ...Array.from(groupTypes.values()).map((groupType) => ({
            value: groupType.group_type_index,
            label: capitalizeFirstLetter(groupType.name_plural || wordPluralize(groupType.group_type)),
        })),
    ]

    const value = customerAnalyticsConfig.account_group_type_index ?? NO_ACCOUNT_GROUP

    return (
        <div className="flex flex-col gap-4">
            <LemonSelect
                data-attr="customer-analytics-account-group-type"
                value={value}
                onChange={(newValue) =>
                    updateCurrentTeam({
                        customer_analytics_config: {
                            account_group_type_index: newValue === NO_ACCOUNT_GROUP ? null : newValue,
                        } as CustomerAnalyticsConfig,
                    })
                }
                disabledReason={currentTeamLoading ? 'Loading...' : restrictedReason}
                fullWidth
                className="max-w-160"
                options={options}
            />
            <LemonDivider />
            <CustomPropertiesConfig />
            <LemonDivider />
            <RelationshipsConfig />
        </div>
    )
}
