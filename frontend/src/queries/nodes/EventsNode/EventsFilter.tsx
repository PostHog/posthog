import { useCallback, useEffect, useMemo, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import api from 'lib/api'

import { EventsQuery } from '~/queries/schema/schema-general'
import { EventDefinitionType } from '~/types'

interface EventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function EventsFilter({ query, setQuery }: EventsFilterProps): JSX.Element {
    const selectedEvents = query.events ?? []
    const [searchOptions, setSearchOptions] = useState<LemonInputSelectOption[]>([])
    const [loading, setLoading] = useState(false)

    const loadEvents = useCallback(async (search?: string): Promise<void> => {
        setLoading(true)
        try {
            const response = await api.eventDefinitions.list({
                search: search || undefined,
                event_type: EventDefinitionType.Event,
                limit: 50,
            })
            setSearchOptions(
                response.results.map((event) => ({
                    key: event.name,
                    label: event.name,
                }))
            )
        } catch {
            setSearchOptions([])
        } finally {
            setLoading(false)
        }
    }, [])

    const debouncedLoadEvents = useDebouncedCallback(loadEvents, 300)

    useEffect(() => {
        void loadEvents()
    }, [loadEvents])

    const options = useMemo(() => {
        const optionKeys = new Set(searchOptions.map((o) => o.key))
        const selectedOptions: LemonInputSelectOption[] = selectedEvents
            .filter((event) => !optionKeys.has(event))
            .map((event) => ({ key: event, label: event }))
        return [...selectedOptions, ...searchOptions]
    }, [searchOptions, selectedEvents])

    return (
        <LemonInputSelect
            mode="multiple"
            value={selectedEvents}
            options={options}
            onChange={(newEvents) => {
                setQuery?.({
                    ...query,
                    events: newEvents.length > 0 ? newEvents : null,
                })
            }}
            onInputChange={(value) => debouncedLoadEvents(value)}
            loading={loading}
            disabled={!setQuery}
            placeholder="Search for events"
            disableFiltering
            size="small"
            data-attr="events-filter-select"
        />
    )
}
