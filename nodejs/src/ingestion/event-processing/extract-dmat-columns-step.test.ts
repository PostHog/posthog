import * as fs from 'fs'
import { DateTime } from 'luxon'
import * as path from 'path'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { MaterializedColumnSlot, PersonMode, ProcessedEvent, ProjectId, TimestampFormat } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { castTimestampOrNow } from '../../utils/utils'
import { EVENTS_OUTPUT } from '../analytics/outputs'
import { isOkResult } from '../pipelines/results'
import { EventToEmit } from './emit-event-step'
import {
    createExtractDmatColumnsStep,
    extractDynamicMaterializedColumns,
    jsonExtractRawAndTrimQuotes,
} from './extract-dmat-columns-step'

function makeEvent(properties: Record<string, unknown>): ProcessedEvent {
    return {
        uuid: 'event-uuid',
        event: '$pageview',
        properties,
        timestamp: castTimestampOrNow('2025-01-01T00:00:00Z', TimestampFormat.ISO),
        team_id: 7,
        project_id: 7 as ProjectId,
        distinct_id: 'user-1',
        elements_chain: '',
        created_at: null,
        captured_at: null,
        person_id: 'person-uuid',
        person_properties: {},
        person_created_at: DateTime.fromISO('2024-12-31T00:00:00Z'),
        person_mode: 'full' as PersonMode,
    }
}

function makeInput(events: ProcessedEvent[], teamId = 7) {
    return {
        eventsToEmit: events.map((event): EventToEmit<typeof EVENTS_OUTPUT> => ({ event, output: EVENTS_OUTPUT })),
        teamId,
        headers: createTestEventHeaders(),
        message: {} as any,
    }
}

describe('extract-dmat-columns-step', () => {
    describe('createExtractDmatColumnsStep', () => {
        it('attaches dmat_columns for every emitted event when slots are configured', async () => {
            const slotManager: Pick<MaterializedColumnSlotManager, 'getSlots'> = {
                getSlots: jest.fn().mockResolvedValue([{ property_name: 'browser', slot_index: 3, state: 'READY' }]),
            }
            const step = createExtractDmatColumnsStep(slotManager)

            const result = await step(makeInput([makeEvent({ browser: 'Chrome', other: 'ignored' })]))

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.eventsToEmit[0].event.dmat_columns).toEqual({ dmat_string_3: 'Chrome' })
            }
            expect(slotManager.getSlots).toHaveBeenCalledWith(7)
        })

        it('no-ops when the manager returns no slots (feature disabled or no slots configured)', async () => {
            const slotManager: Pick<MaterializedColumnSlotManager, 'getSlots'> = {
                getSlots: jest.fn().mockResolvedValue([]),
            }
            const step = createExtractDmatColumnsStep(slotManager)

            const result = await step(makeInput([makeEvent({ browser: 'Chrome' })]))

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.eventsToEmit[0].event.dmat_columns).toBeUndefined()
            }
        })

        it('leaves dmat_columns unset when the configured property is absent on the event', async () => {
            const slotManager: Pick<MaterializedColumnSlotManager, 'getSlots'> = {
                getSlots: jest.fn().mockResolvedValue([{ property_name: 'never_seen', slot_index: 5, state: 'READY' }]),
            }
            const step = createExtractDmatColumnsStep(slotManager)

            const result = await step(makeInput([makeEvent({})]))

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.eventsToEmit[0].event.dmat_columns).toBeUndefined()
            }
        })

        it('extracts onto each event when the batch fans out to multiple outputs', async () => {
            const slotManager: Pick<MaterializedColumnSlotManager, 'getSlots'> = {
                getSlots: jest.fn().mockResolvedValue([{ property_name: 'browser', slot_index: 1, state: 'READY' }]),
            }
            const step = createExtractDmatColumnsStep(slotManager)

            const result = await step(makeInput([makeEvent({ browser: 'Chrome' }), makeEvent({ browser: 'Firefox' })]))

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.eventsToEmit[0].event.dmat_columns).toEqual({ dmat_string_1: 'Chrome' })
                expect(result.value.eventsToEmit[1].event.dmat_columns).toEqual({ dmat_string_1: 'Firefox' })
            }
        })
    })

    describe('extractDynamicMaterializedColumns', () => {
        it('writes string values verbatim into the configured dmat_string column', () => {
            const slots: MaterializedColumnSlot[] = [{ property_name: 'browser', slot_index: 3, state: 'READY' }]

            expect(extractDynamicMaterializedColumns({ browser: 'Chrome', other: 'x' }, slots)).toEqual({
                dmat_string_3: 'Chrome',
            })
        })

        it('populates BACKFILL slots — ingestion must write before the historical mutation runs', () => {
            const slots: MaterializedColumnSlot[] = [{ property_name: 'browser', slot_index: 7, state: 'BACKFILL' }]

            expect(extractDynamicMaterializedColumns({ browser: 'Firefox' }, slots)).toEqual({
                dmat_string_7: 'Firefox',
            })
        })

        it('ignores inherited prototype property names so they cannot break extraction', () => {
            // A slot configured for `constructor` must not pick up Object.prototype.constructor.
            const slots: MaterializedColumnSlot[] = [{ property_name: 'constructor', slot_index: 0, state: 'READY' }]

            expect(extractDynamicMaterializedColumns({ browser: 'Chrome' }, slots)).toEqual({})
        })
    })

    // Parity tests driven by the shared fixture at
    // posthog/temporal/backfill_materialized_property/coercion_fixtures.json. The same fixture is
    // loaded by the Python-side ClickHouse parity test, so any case that passes here MUST also
    // produce the same value when the SQL backfill mutation runs against ClickHouse on the same
    // input — and vice versa. This is the contract we rely on so that a row written live agrees
    // with the same row written by the historical backfill agrees with HogQL's JSON fallback.
    describe('coercion parity vs SQL', () => {
        interface FixtureCase {
            name: string
            input: unknown
            expected_output: unknown
            _skip_reason?: string
        }
        interface Fixtures {
            string_cases: FixtureCase[]
        }

        const fixturePath = path.resolve(
            __dirname,
            '../../../../posthog/temporal/backfill_materialized_property/coercion_fixtures.json'
        )
        const fixtures: Fixtures = parseJSON(fs.readFileSync(fixturePath, 'utf-8'))

        function runCase(fc: FixtureCase): void {
            if (fc._skip_reason) {
                return
            }
            const slot: MaterializedColumnSlot = { property_name: 'p', slot_index: 0, state: 'READY' }
            const actual = extractDynamicMaterializedColumns({ p: fc.input }, [slot])['dmat_string_0']
            // null expected_output ↔ no column written
            if (fc.expected_output === null) {
                expect(actual).toBeUndefined()
            } else {
                expect(actual).toEqual(fc.expected_output)
            }
        }

        it.each(fixtures.string_cases)('String: $name', (fc) => runCase(fc))
    })

    describe('jsonExtractRawAndTrimQuotes', () => {
        it('returns null for null/undefined', () => {
            expect(jsonExtractRawAndTrimQuotes(null)).toBeNull()
            expect(jsonExtractRawAndTrimQuotes(undefined)).toBeNull()
        })

        it('strips the surrounding quotes from string values', () => {
            expect(jsonExtractRawAndTrimQuotes('hello')).toBe('hello')
        })

        it('serializes objects to JSON rather than [object Object]', () => {
            expect(jsonExtractRawAndTrimQuotes({ a: 1 })).toBe('{"a":1}')
        })
    })
})
