import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { HogQLQueryModifiers } from '~/queries/schema'

export interface ModifiersProps<Q extends { response?: Record<string, any>; modifiers?: HogQLQueryModifiers }> {
    setQuery: (query: Q) => void
    query: Q | null
    response: Required<Q>['response'] | null
}

export function Modifiers<Q extends { response?: Record<string, any>; modifiers?: HogQLQueryModifiers }>({
    setQuery,
    query,
    response = null,
}: ModifiersProps<Q>): JSX.Element | null {
    if (query === null) {
        return null
    }
    const labelClassName = 'flex flex-col gap-1 items-start'
    return (
        <div className="flex gap-2">
            <LemonLabel className={labelClassName}>
                <div>POE:</div>
                <LemonSelect
                    options={[
                        { value: 'disabled', label: 'Disabled' },
                        {
                            value: 'person_id_no_override_properties_on_events',
                            label: 'Properties: Events, Person ID: Events',
                        },
                        {
                            value: 'person_id_override_properties_on_events',
                            label: 'Properties: Events, Person ID: Overrides (v2)',
                        },
                        {
                            value: 'person_id_override_properties_joined',
                            label: 'Properties: Person, Person ID: Overrides (v3)',
                        },
                    ]}
                    onChange={(value) =>
                        setQuery({
                            ...query,
                            modifiers: { ...query.modifiers, personsOnEventsMode: value },
                        })
                    }
                    value={query.modifiers?.personsOnEventsMode ?? response?.modifiers?.personsOnEventsMode}
                />
            </LemonLabel>

            <LemonLabel className={labelClassName}>
                <div>In Cohort Via:</div>
                <LemonSelect
                    options={[
                        { value: 'auto', label: 'auto' },
                        { value: 'leftjoin', label: 'leftjoin' },
                        { value: 'subquery', label: 'subquery' },
                        { value: 'leftjoin_conjoined', label: 'leftjoin conjoined' },
                    ]}
                    onChange={(value) =>
                        setQuery({
                            ...query,
                            modifiers: { ...query.modifiers, inCohortVia: value },
                        })
                    }
                    value={query.modifiers?.inCohortVia ?? response?.modifiers?.inCohortVia}
                />
            </LemonLabel>
            <LemonLabel className={labelClassName}>
                <div>Materialization Mode:</div>
                <LemonSelect
                    options={[
                        { value: 'auto', label: 'auto' },
                        { value: 'legacy_null_as_string', label: 'legacy_null_as_string' },
                        { value: 'legacy_null_as_null', label: 'legacy_null_as_null' },
                        { value: 'disabled', label: 'disabled' },
                    ]}
                    onChange={(value) =>
                        setQuery({
                            ...query,
                            modifiers: { ...query.modifiers, materializationMode: value },
                        })
                    }
                    value={query.modifiers?.materializationMode ?? response?.modifiers?.materializationMode}
                />
            </LemonLabel>
            <LemonLabel className={labelClassName}>
                <div>Property Groups:</div>
                <LemonSelect
                    options={[
                        { value: 'enabled', label: 'Enabled' },
                        { value: 'disabled', label: 'Disabled' },
                        { value: 'optimized', label: 'Enabled, with Optimizations' },
                    ]}
                    onChange={(value) =>
                        setQuery({
                            ...query,
                            modifiers: { ...query.modifiers, propertyGroupsMode: value },
                        })
                    }
                    value={query.modifiers?.propertyGroupsMode ?? response?.modifiers?.propertyGroupsMode}
                />
            </LemonLabel>
        </div>
    )
}
