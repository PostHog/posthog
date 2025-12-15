import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import { SelectOption } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AccessControlAction } from '../AccessControlAction'

export function TriggerMatchChoice({
    value,
    onChange,
    resourceType,
    minAccessLevel,
}: {
    value: 'all' | 'any'
    onChange: (value: 'any' | 'all') => void
    resourceType: AccessControlResourceType
    minAccessLevel: AccessControlLevel
}): JSX.Element {
    return (
        <div className="flex flex-col gap-y-1">
            <LemonLabel className="text-base py-2">
                Trigger matching <Since web={{ version: '1.238.0' }} />
            </LemonLabel>
            <div className="flex flex-row gap-x-2 items-center">
                <div>Start when</div>
                <AccessControlAction resourceType={resourceType} minAccessLevel={minAccessLevel}>
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
                                        selectedValue={value}
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
                                        selectedValue={value}
                                    />
                                ),
                            },
                        ]}
                        dropdownMatchSelectWidth={false}
                        data-attr="trigger-match-choice"
                        onChange={onChange}
                        value={value}
                    />
                </AccessControlAction>

                <div>triggers below match</div>
            </div>
        </div>
    )
}
