import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { DataNode, HogQLQuery, HogQLQueryResponse } from '~/queries/schema'

export interface ModifiersProps {
    setQuery: (query: DataNode) => void
    query: HogQLQuery | Record<string, any> | null
    response: HogQLQueryResponse | null
}

export function Modifiers({ setQuery, query, response = null }: ModifiersProps): JSX.Element | null {
    if (query === null) {
        return null
    }
    return (
        <div className="flex gap-2">
            <LemonLabel>
                POE:
                <LemonSelect
                    options={[
                        { value: 'disabled', label: 'Disabled' },
                        {
                            value: 'person_id_no_override_properties_on_events',
                            label: 'Properties: Events, Person ID: Events',
                        },
                        {
                            value: 'person_id_override_properties_on_events_deprecated',
                            label: 'Properties: Events, Person ID: Overrides (v2)',
                        },
                        {
                            value: 'person_id_override_properties_on_events',
                            label: 'Properties: Events, Person ID: Overrides (v3)',
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
                        } as HogQLQuery)
                    }
                    value={query.modifiers?.personsOnEventsMode ?? response?.modifiers?.personsOnEventsMode}
                />
            </LemonLabel>
            <LemonLabel>
                Persons ArgMax:
                <LemonSelect
                    options={[
                        { value: 'v1', label: 'V1' },
                        { value: 'v2', label: 'V2' },
                    ]}
                    onChange={(value) =>
                        setQuery({
                            ...query,
                            modifiers: { ...query.modifiers, personsArgMaxVersion: value },
                        } as HogQLQuery)
                    }
                    value={query.modifiers?.personsArgMaxVersion ?? response?.modifiers?.personsArgMaxVersion}
                />
            </LemonLabel>
            <LemonLabel>
                In Cohort Via:
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
                        } as HogQLQuery)
                    }
                    value={query.modifiers?.inCohortVia ?? response?.modifiers?.inCohortVia}
                />
            </LemonLabel>
            <LemonLabel>
                Materialization Mode:
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
                        } as HogQLQuery)
                    }
                    value={query.modifiers?.materializationMode ?? response?.modifiers?.materializationMode}
                />
            </LemonLabel>
        </div>
    )
}
