import { useCallback, useEffect, useRef, useState } from 'react'

import api from 'lib/api'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { EventsQuery } from '~/queries/schema/schema-general'
import { EventDefinition } from '~/types'

interface EventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function EventsFilter({ query, setQuery }: EventsFilterProps): JSX.Element {
    const events = query.events || []
    const [options, setOptions] = useState<LemonInputSelectOption[]>([])
    const [loading, setLoading] = useState(false)
    const loadedRef = useRef(false)

    const loadEventDefinitions = useCallback(async (search?: string): Promise<void> => {
        setLoading(true)
        try {
            const response = await api.eventDefinitions.list({
                search: search || undefined,
                limit: 50,
            })
            setOptions(
                response.results.map((def: EventDefinition) => ({
                    key: def.name,
                    label: def.name,
                    labelComponent: <PropertyKeyInfo value={def.name} type={TaxonomicFilterGroupType.Events} />,
                }))
            )
            loadedRef.current = true
        } catch {
            setOptions([])
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        void loadEventDefinitions()
    }, [loadEventDefinitions])

    return (
        <LemonInputSelect
            mode="multiple"
            value={events}
            onChange={(newEvents) => {
                setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
            }}
            onFocus={() => {
                if (!loadedRef.current) {
                    void loadEventDefinitions()
                }
            }}
            onInputChange={(value) => {
                void loadEventDefinitions(value)
            }}
            disableFiltering
            options={options}
            placeholder="Filter by event"
            loading={loading}
            size="small"
            disabled={!setQuery}
            data-attr="events-filter-select"
        />
    )
}
