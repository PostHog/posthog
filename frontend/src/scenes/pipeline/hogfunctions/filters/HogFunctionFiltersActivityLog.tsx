import { LemonInputSelect, LemonLabel } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { groupsModel } from '~/models/groupsModel'
import { ActivityScope, FilterType, HogFunctionFiltersType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

function sanitizeActionFilters(filters?: FilterType): Partial<HogFunctionFiltersType> {
    if (!filters) {
        return {}
    }
    const sanitized: HogFunctionFiltersType = {}

    if (filters.events) {
        sanitized.events = filters.events.map((f) => ({
            id: f.id,
            type: 'events',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.actions) {
        sanitized.actions = filters.actions.map((f) => ({
            id: f.id,
            type: 'actions',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    return sanitized
}

export function HogFunctionFiltersActivityLog(): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { configuration } = useValues(hogFunctionConfigurationLogic)

    return (
        <>
            <LemonField name="filters">
                {({ value, onChange }) => (
                    <>
                        <LemonLabel>Scopes</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            options={Object.values(ActivityScope)
                                .sort()
                                .map((x) => ({
                                    key: x,
                                    label: humanizeScope(x),
                                }))}
                            placeholder="Choose which activities to trigger on (leave empty to trigger on all)"
                            value={value?.scope ?? []}
                            onChange={(scope) => onChange({ ...value, scope })}
                        />

                        <LemonLabel>Item IDs</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            options={[]}
                            placeholder="(Optional) Choose specific item IDs to trigger on"
                            value={value?.item_id ?? []}
                            onChange={(item_id) => onChange({ ...value, item_id })}
                            allowCustomValues
                        />

                        <LemonLabel>Activity types</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            options={[]}
                            placeholder="(Optional) The kind of activity to trigger on"
                            value={value?.activity ?? []}
                            onChange={(activity) => onChange({ ...value, activity })}
                            allowCustomValues
                        />
                    </>
                )}
            </LemonField>
        </>
    )
}
