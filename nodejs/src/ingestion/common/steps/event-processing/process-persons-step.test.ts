import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogUnprocessablePersonError } from '~/common/personhog/persons'
import { PersonhogPersonsStore } from '~/ingestion/common/persons/personhog-persons-store'
import { PipelineResultType } from '~/ingestion/framework/results'
import { withStepRetry } from '~/ingestion/framework/retry'
import { PluginEvent } from '~/plugin-scaffold'
import { InternalPerson, Team } from '~/types'

import { EventPipelineRunnerOptions } from './event-pipeline-options'
import { ProcessPersonsInput, createProcessPersonsStep } from './process-persons-step'

type EventFields = Pick<PluginEvent, 'event' | 'properties'>

describe('createProcessPersonsStep with the personhog store', () => {
    const TEAM_ID = 1
    const DISTINCT_ID = 'known-id'
    const PERSON_ID = '7'
    const TIMESTAMP = '2026-08-07T00:00:00Z'

    const options: EventPipelineRunnerOptions = {
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
        PERSON_MERGE_ASYNC_ENABLED: false,
        PERSON_MERGE_SYNC_BATCH_SIZE: 1,
        PERSON_MERGE_FOLD_ENABLED: false,
        PERSON_MERGE_FOLD_TEAM_ALLOWLIST: '*',
        PERSONHOG_IDENTITY_EMITS_MERGE_WARNINGS: false,
        PERSON_MERGE_NOT_APPLIED_WAIT_MS: 0,
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
        PERSON_PROPERTIES_UPDATE_ALL: false,
        FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS: '*',
        FLAG_CALLED_PERSONLESS_EXCLUDED_TEAMS: '',
        EXPERIMENT_EXPOSURE_DUPLICATION_TEAMS: '',
    }

    const person: InternalPerson = {
        id: PERSON_ID,
        uuid: 'person-uuid',
        team_id: TEAM_ID,
        properties: {},
        created_at: DateTime.fromMillis(3_600_000, { zone: 'utc' }),
        version: 1,
        is_user_id: null,
        is_identified: false,
        last_seen_at: null,
    }

    let repository: jest.Mocked<PersonHogPersonWriteRepository>
    let store: PersonhogPersonsStore

    beforeEach(() => {
        repository = {
            resolvePersonsByDistinctIds: jest.fn((keys: { teamId: number; distinctId: string }[]) =>
                Promise.resolve(
                    keys.map(({ teamId, distinctId }) => ({
                        teamId,
                        distinctId,
                        person: distinctId === DISTINCT_ID ? person : null,
                    }))
                )
            ),
            fetchPersonById: jest.fn(),
            updatePersonProperties: jest.fn(),
            mergePersons: jest.fn(),
            getOrCreatePersonByDistinctId: jest.fn(),
        } as unknown as jest.Mocked<PersonHogPersonWriteRepository>
        repository.resolvePersonIdsByDistinctIds = jest.fn((keys, callerTag) =>
            repository.resolvePersonsByDistinctIds(keys, callerTag).then((results) =>
                results.map(({ teamId, distinctId, person }) => ({
                    teamId,
                    distinctId,
                    personId: person?.id ?? null,
                }))
            )
        ) as never
        store = new PersonhogPersonsStore(repository)
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const settle = async <T>(pending: Promise<T>): Promise<T> => {
        await jest.advanceTimersByTimeAsync(60_000)
        return await pending
    }

    const runStep = async (event: EventFields, { prefetch }: { prefetch: boolean }) => {
        const normalizedEvent: PluginEvent = {
            uuid: 'event-uuid',
            distinct_id: DISTINCT_ID,
            team_id: TEAM_ID,
            ip: null,
            site_url: '',
            now: TIMESTAMP,
            timestamp: TIMESTAMP,
            ...event,
        }
        if (prefetch) {
            await store.prefetchPersons([{ teamId: TEAM_ID, distinctId: DISTINCT_ID, batchId: 0 }])
        }
        const input: ProcessPersonsInput = {
            normalizedEvent,
            team: { id: TEAM_ID } as Team,
            timestamp: DateTime.fromISO(TIMESTAMP),
            personsStoreForBatch: store.forBatch(0),
            mergeFold: { type: 'immediate' },
        }
        const step = withStepRetry(
            createProcessPersonsStep(options, { queueMessages: jest.fn().mockResolvedValue(undefined) } as never),
            { tries: 5, sleepMs: 1, name: 'process_persons' }
        )
        return await step(input)
    }

    const refusal = 'stored person properties cannot be parsed'
    const events: [string, EventFields][] = [
        ['a $set event', { event: '$set', properties: { $set: { plan: 'pro' } } }],
        ['an $identify', { event: '$identify', properties: { $anon_distinct_id: 'anon-id', $set: { plan: 'pro' } } }],
    ]
    const cases = events.flatMap(([name, event]) =>
        [true, false].map((prefetch) => ({ name, event, prefetch, read: prefetch ? 'a prefetch' : 'no prefetch' }))
    )

    it.each(cases)(
        'drops $name with $read when the leader cannot parse the stored person',
        async ({ event, prefetch }) => {
            repository.fetchPersonById.mockRejectedValue(
                new PersonhogUnprocessablePersonError(refusal, TEAM_ID, PERSON_ID)
            )
            repository.mergePersons.mockRejectedValue(new ConnectError(refusal, Code.DataLoss))

            const result = await settle(runStep(event, { prefetch }))
            await settle(store.flush())

            expect(result).toMatchObject({
                type: PipelineResultType.DROP,
                reason: 'unprocessable_person',
                warnings: [
                    {
                        type: 'person_properties_depth_violation',
                        details: {
                            distinctId: DISTINCT_ID,
                            eventUuid: 'event-uuid',
                            message: expect.stringContaining('Delete this person'),
                        },
                        key: DISTINCT_ID,
                    },
                ],
            })
            expect(repository.fetchPersonById).toHaveBeenCalledTimes(prefetch ? 2 : 1)
            expect(repository.updatePersonProperties).not.toHaveBeenCalled()
            expect(repository.getOrCreatePersonByDistinctId).not.toHaveBeenCalled()
        }
    )

    it('keeps the DLQ for a non-retriable error of another kind', async () => {
        repository.fetchPersonById.mockRejectedValue(
            Object.assign(new Error('another refusal'), { isRetriable: false })
        )

        const result = await settle(
            runStep({ event: '$set', properties: { $set: { plan: 'pro' } } }, { prefetch: false })
        )

        expect(result).toMatchObject({ type: PipelineResultType.DLQ, reason: 'Processing error - non-retriable' })
    })
})
