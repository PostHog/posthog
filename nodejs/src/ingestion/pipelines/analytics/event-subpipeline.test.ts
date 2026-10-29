import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { EVENTS_OUTPUT } from '~/common/outputs'
import { PersonMessage } from '~/common/persons/person-message'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { newCommonIngestionPipeline } from '~/ingestion/common/common-ingestion-pipeline'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { createImmediateMergeFoldStep } from '~/ingestion/common/persons/person-merge-fold'
import { EventOps, refineEventOps } from '~/ingestion/common/persons/person-update'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { createTopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { createTestTeam } from '~/tests/helpers/team'
import { createNoopTopHog } from '~/tests/helpers/tophog'
import { InternalPerson, RawKafkaEvent } from '~/types'

import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'

describe('event subpipeline person snapshots', () => {
    it.each(['personful', 'personless', 'restricted'] as const)(
        'preserves successive snapshots through parsing, person processing and emission (%s)',
        async (mode) => {
            const team = createTestTeam()
            const now = '2026-01-01T12:00:00Z'
            let storedPerson: InternalPerson = {
                id: '1',
                uuid: new UUIDT().toString(),
                team_id: team.id,
                properties: { destination_only: true, plan: 'destination' },
                created_at: DateTime.fromISO(now),
                is_identified: true,
                is_user_id: null,
                version: 1,
                last_seen_at: null,
                properties_last_updated_at: {},
                properties_last_operation: {},
            }
            const personsStoreForBatch = {
                fetchForChecking: () =>
                    Promise.resolve({ ...storedPerson, properties: { ...storedPerson.properties } }),
                fetchForUpdate: () => Promise.resolve(storedPerson),
                applyEventOps: (person: InternalPerson, ops: EventOps): Promise<[InternalPerson, PersonMessage[]]> => {
                    const updates = refineEventOps(ops, person.properties)
                    storedPerson = { ...person, properties: { ...person.properties, ...updates.toSet } }
                    for (const key of updates.toUnset) {
                        delete storedPerson.properties[key]
                    }
                    return Promise.resolve([storedPerson, []])
                },
            } as unknown as PersonsStoreForBatch
            const teamManager = {
                getTeamByToken: () => Promise.resolve(team),
            } as unknown as TeamManager
            const hogTransformer = {
                transformEventAndProduceMessages: (event: PluginEvent) =>
                    Promise.resolve({
                        event: {
                            ...event,
                            properties: { ...event.properties, $set: { transformation_only: true } },
                        },
                        invocationResults: [],
                    }),
            } as unknown as HogTransformer
            const outputs = createMockIngestionOutputs<string>()
            const promiseScheduler = new PromiseScheduler()
            const topHog = createNoopTopHog()
            type Input = Omit<EventSubpipelineInput, 'event' | 'team' | 'headers'>
            const pipeline = newCommonIngestionPipeline<Input, { message: Message }, string>({
                outputs,
                teamManager,
                promiseScheduler,
                topHog,
            })
                .parseHeaders()
                .parseMessage()
                .resolveTeam()
                .pipe(createImmediateMergeFoldStep())
                .concurrentlyPerGroup(
                    (input) => input.event.distinct_id,
                    (group) =>
                        group.sequentially((event) =>
                            createEventSubpipeline(event, {
                                options: {
                                    ...getDefaultIngestionConsumerConfig(),
                                    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: true,
                                },
                                outputs,
                                teamManager,
                                groupTypeManager: {} as GroupTypeManager,
                                hogTransformer,
                                topHog: createTopHogWrapper(topHog),
                            })
                        )
                )
                .build()

            const snapshots = [{ plan: 'paid', nested: { source: true } }, { plan: 'free' }, {}, { plan: 'paid' }]
            const batch = snapshots.map((snapshot) => {
                const message = createTestMessage({
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: new UUIDT().toString(),
                            data: JSON.stringify({
                                event: '$pageview',
                                distinct_id: 'example-user',
                                timestamp: now,
                                person_properties_mode: 'snapshot',
                                person_properties: snapshot,
                                properties: { $browser: 'Chrome', $process_person_profile: mode !== 'personless' },
                            }),
                        })
                    ),
                    headers: [
                        { token: Buffer.from(team.api_token) },
                        { timestamp: Buffer.from(now) },
                        { now: Buffer.from(now) },
                        { force_disable_person_processing: Buffer.from(String(mode === 'restricted')) },
                    ],
                })
                return createOkContext(
                    {
                        message,
                        personsStoreForBatch,
                        groupStoreForBatch: {} as GroupStoreForBatch,
                        eventUsageBatch: new UsageRecordBatch(null, { unit: 'events', isTeamEnabled: () => false }),
                    },
                    { message }
                )
            })
            expect(await pipeline.feed(batch, {})).toMatchObject({ ok: true })
            for (let result = await pipeline.next(); result !== null; result = await pipeline.next()) {
                expect(result.elements.every((element) => isOkResult(element.result))).toBe(true)
            }
            await promiseScheduler.waitForAll()

            const emitted = outputs.produce.mock.calls
                .filter(([output]) => output === EVENTS_OUTPUT)
                .map(([, message]) => parseJSON(message.value!.toString()) as RawKafkaEvent)
            expect(emitted.map((event) => parseJSON(event.person_properties!))).toEqual(
                mode === 'personful' ? snapshots : snapshots.map(() => ({}))
            )
            for (const event of emitted) {
                expect(event.historical_migration).toBeUndefined()
                expect(parseJSON(event.properties!)).toMatchObject({ $browser: 'Chrome' })
                expect(parseJSON(event.properties!)).not.toHaveProperty('$set')
                expect(parseJSON(event.properties!)).not.toHaveProperty('$set_once')
            }
            expect(storedPerson.properties).toEqual(
                mode === 'personful'
                    ? { destination_only: true, plan: 'paid', nested: { source: true } }
                    : { destination_only: true, plan: 'destination' }
            )
        }
    )
})
