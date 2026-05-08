import * as fs from 'fs'
import { DateTime } from 'luxon'
import * as path from 'path'

import { MaterializedColumnSlot, Person, PreIngestionEvent, ProjectId, TimestampFormat } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { castTimestampOrNow } from '../../utils/utils'
import { createEvent } from './create-event'

const baseEvent: PreIngestionEvent = {
    eventUuid: 'event-uuid',
    event: '$pageview',
    teamId: 7,
    projectId: 7 as ProjectId,
    distinctId: 'user-1',
    properties: {},
    timestamp: castTimestampOrNow('2025-01-01T00:00:00Z', TimestampFormat.ISO),
}

const fakePerson: Person = {
    team_id: 7,
    properties: {},
    uuid: 'person-uuid',
    created_at: DateTime.fromISO('2024-12-31T00:00:00Z'),
    force_upgrade: false,
}

describe('createEvent dmat extraction', () => {
    it('does not attach dmat_columns when no slots are configured', () => {
        const event = createEvent(
            { ...baseEvent, properties: { browser: 'Chrome' } },
            fakePerson,
            true,
            false,
            null,
            []
        )

        expect(event.dmat_columns).toBeUndefined()
    })

    it('writes string values verbatim into the configured dmat_string column', () => {
        const slots: MaterializedColumnSlot[] = [
            {
                property_name: 'browser',
                slot_index: 3,
                state: 'READY',
                compaction_target_slot_index: null,
            },
        ]

        const event = createEvent(
            { ...baseEvent, properties: { browser: 'Chrome', other: 'ignored' } },
            fakePerson,
            true,
            false,
            null,
            slots
        )

        expect(event.dmat_columns).toEqual({ dmat_string_3: 'Chrome' })
    })

    it('skips properties that are missing on the event', () => {
        const slots: MaterializedColumnSlot[] = [
            {
                property_name: 'never_seen',
                slot_index: 5,
                state: 'READY',
                compaction_target_slot_index: null,
            },
        ]

        const event = createEvent({ ...baseEvent, properties: {} }, fakePerson, true, false, null, slots)

        expect(event.dmat_columns).toBeUndefined()
    })

    it('dual-writes to both old and new columns when compaction_target_slot_index is set', () => {
        // The slot is being repacked from column 7 → column 2. Until the workflow swaps after
        // the mutation completes, both columns must be populated for new events: the old one
        // because HogQL still reads from it, and the new one so the historical-data mutation
        // doesn't overwrite live values.
        const slots: MaterializedColumnSlot[] = [
            {
                property_name: 'browser',
                slot_index: 7,
                state: 'READY',
                compaction_target_slot_index: 2,
            },
        ]

        const event = createEvent(
            { ...baseEvent, properties: { browser: 'Safari' } },
            fakePerson,
            true,
            false,
            null,
            slots
        )

        expect(event.dmat_columns).toEqual({
            dmat_string_7: 'Safari',
            dmat_string_2: 'Safari',
        })
    })

    it('writes BACKFILL slots — ingestion has to populate before the historical mutation runs', () => {
        const slots: MaterializedColumnSlot[] = [
            {
                property_name: 'browser',
                slot_index: 7,
                state: 'BACKFILL',
                compaction_target_slot_index: null,
            },
        ]

        const event = createEvent(
            { ...baseEvent, properties: { browser: 'Firefox' } },
            fakePerson,
            true,
            false,
            null,
            slots
        )

        expect(event.dmat_columns).toEqual({ dmat_string_7: 'Firefox' })
    })
})

// Parity tests driven by the shared fixture at
// posthog/temporal/backfill_materialized_property/coercion_fixtures.json. The same fixture is
// loaded by the Python-side ClickHouse parity test, so any case that passes here MUST also
// produce the same value when the SQL backfill mutation runs against ClickHouse on the same
// input — and vice versa. This is the contract we rely on so that a row written live agrees
// with the same row written by the historical backfill agrees with HogQL's JSON fallback.
describe('createEvent dmat coercion parity vs SQL', () => {
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
        const slot: MaterializedColumnSlot = {
            property_name: 'p',
            slot_index: 0,
            state: 'READY',
            compaction_target_slot_index: null,
        }
        const event = createEvent({ ...baseEvent, properties: { p: fc.input } }, fakePerson, true, false, null, [slot])
        const actual = event.dmat_columns?.['dmat_string_0']
        // null expected_output ↔ no column written
        if (fc.expected_output === null) {
            expect(actual).toBeUndefined()
        } else {
            expect(actual).toEqual(fc.expected_output)
        }
    }

    fixtures.string_cases.forEach((fc) => {
        it(`String: ${fc.name}`, () => runCase(fc))
    })
})
