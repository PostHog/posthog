import type { EventsScanWarning, HogQLQueryResponse } from '~/queries/schema/schema-general'

import { eventsScanWarningMessage, eventsScanWarningMessages } from './eventsScanWarning'

describe('eventsScanWarning', () => {
    const scanWarning = (message: string, start: number): EventsScanWarning => ({
        type: 'events_scan',
        reason: 'no_time_bound',
        source: 'query',
        message,
        start,
        end: start + 6,
    })
    const noTimeBound = 'This query has no timestamp filter on events.'
    const noEventFilter = 'This query reads every event in its date range.'

    it('reports each distinct message once, whatever the query reads twice', () => {
        // A self-join, or a CTE plus its outer select, produces one finding per read of `events`.
        // The offsets differ, but no surface renders them, so the repeats read as the same advice twice.
        const warnings: HogQLQueryResponse['warnings'] = [
            scanWarning(noEventFilter, 20),
            scanWarning(noTimeBound, 20),
            scanWarning(noEventFilter, 34),
            scanWarning(noTimeBound, 34),
        ]

        expect(eventsScanWarningMessages(warnings)).toEqual([noEventFilter, noTimeBound])
        expect(eventsScanWarningMessage(warnings)).toEqual(`${noEventFilter} ${noTimeBound}`)
    })

    it.each([
        ['no warnings', undefined],
        ['an empty list', []],
        [
            'only other warning kinds',
            [
                {
                    type: 'warehouse_sync' as const,
                    table_name: 't',
                    schema_name: 's',
                    source_type: 'Stripe',
                    status: 'Failed',
                    message: 'The sync failed.',
                },
            ],
        ],
    ])('finds nothing to say for %s', (_label, warnings) => {
        expect(eventsScanWarningMessages(warnings as HogQLQueryResponse['warnings'])).toEqual([])
        expect(eventsScanWarningMessage(warnings as HogQLQueryResponse['warnings'])).toBeNull()
    })
})
