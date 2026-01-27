import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import { SelectOption } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { AccessControlLevel } from '~/types'

import { AccessControlAction } from '../AccessControlAction'
import { ingestionControlsLogic } from './ingestionControlsLogic'

export function MatchTypeSelect(): JSX.Element {
    const { resourceType, matchType } = useValues(ingestionControlsLogic)
    const { onChangeMatchType } = useActions(ingestionControlsLogic)

    return (
        <div className="flex flex-col gap-y-1">
            <LemonLabel className="text-base py-2">
                Trigger matching <Since web={{ version: '1.238.0' }} />
            </LemonLabel>
            <div className="flex flex-row gap-x-2 items-center">
                <div>Start when</div>
                <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
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
                                        selectedValue={matchType}
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
                                        selectedValue={matchType}
                                    />
                                ),
                            },
                        ]}
                        dropdownMatchSelectWidth={false}
                        data-attr="trigger-match-choice"
                        onChange={onChangeMatchType}
                        value={matchType}
                    />
                </AccessControlAction>

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
