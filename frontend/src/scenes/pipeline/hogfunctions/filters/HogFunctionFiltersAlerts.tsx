import { useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { groupsModel } from '~/models/groupsModel'
import { FilterType, HogFunctionFiltersType } from '~/types'

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

export function HogFunctionFiltersAlerts(): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { configuration } = useValues(hogFunctionConfigurationLogic)

    return (
        <>
            <LemonField name="filters" label="Linked alerts">
                {({ value, onChange }) => (
                    <>
                        <p>Coming soon!</p>
                    </>
                )}
            </LemonField>
        </>
    )
}
