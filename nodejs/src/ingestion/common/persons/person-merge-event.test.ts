import { murmur2Partition } from '~/common/kafka/murmur2'
import { parseJSON } from '~/common/utils/json-parse'

import { MERGE_EVENT_SCHEMA_VERSION, buildPersonMergeEventMessage } from './person-merge-event'

describe('buildPersonMergeEventMessage', () => {
    const teamId = 2
    const oldPersonUuid = '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee'
    const newPersonUuid = '01928bbb-cccc-dddd-eeee-ffffffffffff'
    const mergedAtMs = 1716800000000

    function build() {
        return buildPersonMergeEventMessage(teamId, oldPersonUuid, newPersonUuid, mergedAtMs, 64)
    }

    function decode(value: Buffer): Record<string, unknown> {
        return parseJSON(value.toString())
    }

    it('keys by team_id and P_old (the deleted person)', () => {
        expect(build().key).toBe(`${teamId}:${oldPersonUuid}`)
    })

    it('partitions with Kafka murmur2 over the key', () => {
        const { key, partition } = build()
        expect(partition).toBe(murmur2Partition(key, 64))
        // The Rust partitioner places this exact key at partition 58 (see murmur2.test.ts fixture).
        expect(partition).toBe(58)
    })

    it('serializes exactly the keys the Rust PersonMergeEvent decodes', () => {
        const decoded = decode(build().value)
        expect(Object.keys(decoded).sort()).toEqual([
            'merged_at_ms',
            'new_person_uuid',
            'old_person_uuid',
            'schema_version',
            'team_id',
        ])
    })

    it('pins schema_version to 1', () => {
        expect(decode(build().value).schema_version).toBe(1)
        expect(MERGE_EVENT_SCHEMA_VERSION).toBe(1)
    })

    it('carries the merge identities and timestamp verbatim', () => {
        const decoded = decode(build().value)
        expect(decoded.team_id).toBe(teamId)
        expect(decoded.old_person_uuid).toBe(oldPersonUuid)
        expect(decoded.new_person_uuid).toBe(newPersonUuid)
        expect(decoded.merged_at_ms).toBe(mergedAtMs)
    })

    it('encodes numeric fields as numbers, not strings (serde i32/i64/u32 reject strings)', () => {
        const decoded = decode(build().value)
        expect(typeof decoded.team_id).toBe('number')
        expect(typeof decoded.merged_at_ms).toBe('number')
        expect(typeof decoded.schema_version).toBe('number')
    })

    it('is partition-stable for the same inputs', () => {
        expect(build().partition).toBe(build().partition)
    })
})
