import { Message } from 'node-rdkafka'

import { defaultConfig } from '../../../common/config/config'
import { PluginsServerConfig } from '../../../types'
import {
    DeadLetterRecord,
    ReplayPolicy,
    readDeadLetterRecord,
    readReplayPolicy,
    replayTargetIds,
    shouldReplay,
} from './replay-policy'

describe('replay-policy', () => {
    const PARKED_AT = Date.parse('2026-09-01T00:00:00.000Z')
    const NOW = Date.parse('2026-09-08T00:00:00.000Z')

    const openPolicy = (overrides: Partial<ReplayPolicy> = {}): ReplayPolicy => ({
        steps: [],
        from: null,
        to: null,
        maxAgeMs: 30 * 24 * 60 * 60 * 1000,
        teamIds: [],
        skipTeamIds: [],
        hogFunctionIds: [],
        reasonContains: '',
        ...overrides,
    })

    const record = (overrides: Partial<DeadLetterRecord> = {}): DeadLetterRecord => ({
        step: 'inputs',
        reason: 'Invalid arguments for builtin round',
        timestamp: PARKED_AT,
        teamId: 2,
        eventUuid: 'event-1',
        hogFunctionIds: ['fn-1'],
        hogFlowIds: [],
        ...overrides,
    })

    describe('readDeadLetterRecord', () => {
        it('reads a record from headers without touching the payload', () => {
            const message = {
                value: Buffer.from('{"uuid":"event-1"}'),
                headers: [
                    { dlq_step: Buffer.from('inputs') },
                    { dlq_reason: Buffer.from('boom') },
                    { dlq_timestamp: Buffer.from('2026-09-01T00:00:00.000Z') },
                    { dlq_team_id: Buffer.from('2') },
                    { dlq_event_uuid: Buffer.from('event-1') },
                    { dlq_hog_function_ids: Buffer.from('fn-1,fn-2') },
                    { dlq_hog_flow_ids: Buffer.from('') },
                    { dlq_replay_count: Buffer.from('1') },
                ],
            } as unknown as Message

            expect(readDeadLetterRecord(message)).toEqual({
                step: 'inputs',
                reason: 'boom',
                timestamp: PARKED_AT,
                teamId: 2,
                eventUuid: 'event-1',
                hogFunctionIds: ['fn-1', 'fn-2'],
                hogFlowIds: [],
            })
        })

        it.each([
            ['a message with no dlq headers', { value: Buffer.from('{}'), headers: [] }],
            ['a message with no payload', { value: null, headers: [{ dlq_step: Buffer.from('inputs') }] }],
        ])('returns null for %s', (_name, message) => {
            expect(readDeadLetterRecord(message as unknown as Message)).toBeNull()
        })
    })

    describe('shouldReplay', () => {
        it('replays a record an open policy matches', () => {
            expect(shouldReplay(record(), openPolicy(), NOW)).toEqual({ replay: true })
        })

        it.each([
            ['unreadable', null, openPolicy()],
            ['step', record({ step: 'filter' }), openPolicy({ steps: ['inputs'] })],
            ['window', record(), openPolicy({ from: Date.parse('2026-09-02T00:00:00.000Z') })],
            ['window', record(), openPolicy({ to: Date.parse('2026-08-30T00:00:00.000Z') })],
            ['max_age', record(), openPolicy({ maxAgeMs: 60 * 60 * 1000 })],
            ['team', record(), openPolicy({ skipTeamIds: [2] })],
            ['team', record(), openPolicy({ teamIds: [3] })],
            ['team', record({ teamId: null }), openPolicy({ teamIds: [2] })],
            ['reason', record(), openPolicy({ reasonContains: 'now(' })],
            ['function', record(), openPolicy({ hogFunctionIds: ['fn-9'] })],
        ])('skips with reason %s', (skipReason, rec, policy) => {
            expect(shouldReplay(rec, policy, NOW)).toEqual({ replay: false, skipReason })
        })
    })

    describe('readReplayPolicy', () => {
        // Built from the real defaults rather than a cast partial, so a new required key or a
        // changed default shows up here instead of being hidden behind the cast.
        const envConfig = (overrides: Partial<PluginsServerConfig> = {}): PluginsServerConfig => ({
            ...defaultConfig,
            ...overrides,
        })

        it('leaves every list empty when nothing is configured', () => {
            // `Number('')` is 0, so a list built without dropping empties reads as "team 0 only"
            // and a run with no team filter replays nothing at all.
            expect(readReplayPolicy(envConfig())).toEqual({
                steps: [],
                from: null,
                to: null,
                maxAgeMs: defaultConfig.CDP_DLQ_REPLAY_MAX_AGE_HOURS * 60 * 60 * 1000,
                teamIds: [],
                skipTeamIds: [],
                hogFunctionIds: [],
                reasonContains: '',
            })
        })

        it('reads the lists and the window when they are configured', () => {
            const policy = readReplayPolicy(
                envConfig({
                    CDP_DLQ_REPLAY_STEPS: 'inputs, filter',
                    CDP_DLQ_REPLAY_TEAM_IDS: '2, 3',
                    CDP_DLQ_REPLAY_SKIP_TEAM_IDS: '9',
                    CDP_DLQ_REPLAY_HOG_FUNCTION_IDS: 'fn-1,fn-2',
                    CDP_DLQ_REPLAY_FROM: '2026-09-01T00:00:00.000Z',
                    CDP_DLQ_REPLAY_TO: '2026-09-02T00:00:00.000Z',
                })
            )

            expect(policy).toMatchObject({
                steps: ['inputs', 'filter'],
                teamIds: [2, 3],
                skipTeamIds: [9],
                hogFunctionIds: ['fn-1', 'fn-2'],
                from: Date.parse('2026-09-01T00:00:00.000Z'),
                to: Date.parse('2026-09-02T00:00:00.000Z'),
            })
        })
    })

    describe('replayTargetIds', () => {
        it('restricts the rebuild to the sources the record names', () => {
            const targets = replayTargetIds(record({ hogFunctionIds: ['fn-1'], hogFlowIds: ['flow-1'] }), openPolicy())
            expect(targets).toEqual(new Set(['fn-1', 'flow-1']))
        })

        it('allows every source only when the record names none', () => {
            expect(replayTargetIds(record({ hogFunctionIds: [], hogFlowIds: [] }), openPolicy())).toBeNull()
        })

        it('intersects the record with the policy, so a narrowed run cannot widen it', () => {
            const targets = replayTargetIds(
                record({ hogFunctionIds: ['fn-1', 'fn-2'] }),
                openPolicy({ hogFunctionIds: ['fn-2', 'fn-3'] })
            )
            expect(targets).toEqual(new Set(['fn-2']))
        })

        it('holds a policy-restricted run to its own ids when the record names none', () => {
            const targets = replayTargetIds(
                record({ hogFunctionIds: [], hogFlowIds: [] }),
                openPolicy({ hogFunctionIds: ['fn-2'] })
            )
            expect(targets).toEqual(new Set(['fn-2']))
        })
    })
})
