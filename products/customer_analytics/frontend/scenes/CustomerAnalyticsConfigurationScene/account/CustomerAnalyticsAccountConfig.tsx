import { useActions, useValues } from 'kea'

import { LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Separator } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { capitalizeFirstLetter, wordPluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { CustomerAnalyticsConfig } from '~/queries/schema/schema-general'

import { GroupsIntroduction } from 'products/groups/frontend/components/GroupsIntroduction'

import { CustomPropertiesConfig } from './CustomPropertiesConfig'
import { DefaultPinnedAccountProperties } from './DefaultPinnedAccountProperties'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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

    const handleAccountGroupChange = (newValue: number): void =>
        updateCurrentTeam({
            customer_analytics_config: {
                account_group_type_index: newValue === NO_ACCOUNT_GROUP ? null : newValue,
            } as CustomerAnalyticsConfig,
        })

    const selectDisabledReason = currentTeamLoading ? 'Loading...' : restrictedReason

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <Select value={value} onValueChange={(newValue) => handleAccountGroupChange(newValue as number)}>
                    <SelectTrigger
                        aria-label="Account group type"
                        className="w-full max-w-160"
                        disabledReason={selectDisabledReason}
                        data-attr="customer-analytics-account-group-type"
                    >
                        <SelectValue>
                            {(selected: number) => options.find((option) => option.value === selected)?.label}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {options.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Separator />
                <DefaultPinnedAccountProperties />
                <Separator />
                <CustomPropertiesConfig />
                <Separator />
                <RelationshipsConfig />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <LemonSelect
                data-attr="customer-analytics-account-group-type"
                value={value}
                onChange={handleAccountGroupChange}
                disabledReason={selectDisabledReason}
                fullWidth
                className="max-w-160"
                options={options}
            />
            <LemonDivider />
            <DefaultPinnedAccountProperties />
            <LemonDivider />
            <CustomPropertiesConfig />
            <LemonDivider />
            <RelationshipsConfig />
        </div>
    )
}
