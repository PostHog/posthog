import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { TeamMembershipLevel } from 'lib/constants'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import { SelectOption } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'

import { RestrictionScope, useRestrictedArea } from '../RestrictedArea'
import { ingestionControlsLogic } from './ingestionControlsLogic'

interface MatchTypeSelectProps {
    lockedToAllReason?: string
}

export function MatchTypeSelect({ lockedToAllReason }: MatchTypeSelectProps = {}): JSX.Element {
    const { matchType } = useValues(ingestionControlsLogic)
    const { onChangeMatchType } = useActions(ingestionControlsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const displayedValue = lockedToAllReason ? 'all' : matchType
    const disabledReason = lockedToAllReason ?? restrictedReason

    return (
        <div className="flex flex-col gap-y-1">
            <LemonLabel className="text-base py-2">
                Trigger matching <Since web={{ version: '1.238.0' }} />
            </LemonLabel>
            <div className="flex flex-row gap-x-2 items-center">
                <div>Start when</div>
                <LemonSelect
                    options={[
                        {
                            label: 'all',
                            value: 'all',
                            labelInMenu: (
                                <SelectOption
                                    title="All"
                                    description="Every trigger must match"
                                    value="all"
                                    selectedValue={displayedValue}
                                />
                            ),
                        },
                        {
                            label: 'any',
                            value: 'any',
                            labelInMenu: (
                                <SelectOption
                                    title="Any"
                                    description="One or more triggers must match"
                                    value="any"
                                    selectedValue={displayedValue}
                                />
                            ),
                        },
                    ]}
                    dropdownMatchSelectWidth={false}
                    data-attr="trigger-match-choice"
                    onChange={onChangeMatchType}
                    value={displayedValue}
                    disabledReason={disabledReason}
                />

                <div>triggers below match</div>
            </div>
        </div>
    )
}

export function MatchTypeTag(): JSX.Element {
    const { matchType } = useValues(ingestionControlsLogic)

    // Let's follow PostHog style of AND / OR from funnels
    return (
        <LemonTag type="danger" className="my-2 mr-2">
            {matchType === 'any' ? 'OR' : 'AND'}
        </LemonTag>
    )
}
