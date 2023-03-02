import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import {
    capture,
    createOrganization,
    createTeam,
    fetchPerformanceEvents,
    fetchSessionRecordingsEvents,
    getMetric,
} from './api'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

let kafka: Kafka
let organizationId: string

let dlq: KafkaMessage[]
let dlqConsumer: Consumer

beforeAll(async () => {
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })

    dlq = []
    dlqConsumer = kafka.consumer({ groupId: 'session_recording_events_test' })
    await dlqConsumer.subscribe({ topic: 'session_recording_events_dlq' })
    await dlqConsumer.run({
        eachMessage: ({ message }) => {
            dlq.push(message)
            return Promise.resolve()
        },
    })

    organizationId = await createOrganization()
})

afterAll(async () => {
    await Promise.all([await dlqConsumer.disconnect()])
})

test.concurrent(
    `snapshot captured, processed, ingested via events_plugin_ingestion topic`,
    async () => {
        // We have switched from pushing the `events_plugin_ingestion` to
        // pushing to `session_recording_events`. There will still be session
        // recording events in the `events_plugin_ingestion` topic for a while
        // so we need to still handle these events with the current consumer.
        // TODO: we push recording events that we get from
        // `events_plugin_ingestion` to `session_recording_events`. We should be
        // able to remove this push and this test once we know there are no more
        // recording events in `events_plugin_ingestion`.
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$snapshot',
            properties: {
                $session_id: '1234abc',
                $window_id: 'abc1234',
                $snapshot_data: 'yes way',
            },
        })

        const events = await waitForExpect(async () => {
            const events = await fetchSessionRecordingsEvents(teamId)
            expect(events.length).toBe(1)
            return events
        })

        expect(events[0]).toEqual({
            _offset: expect.any(Number),
            _timestamp: expect.any(String),
            click_count: 0,
            created_at: expect.any(String),
            distinct_id: distinctId,
            events_summary: [],
            first_event_timestamp: null,
            has_full_snapshot: 0,
            keypress_count: 0,
            last_event_timestamp: null,
            session_id: '1234abc',
            snapshot_data: 'yes way',
            team_id: teamId,
            timestamp: expect.any(String),
            timestamps_summary: [],
            urls: [],
            uuid: uuid,
            window_id: 'abc1234',
        })
    },
    20000
)

test.concurrent(
    `snapshot captured, processed, ingested via session_recording_events topic with no team_id set`,
    async () => {
        // We have switched from pushing the `events_plugin_ingestion` to
        // pushing to `session_recording_events`. There will still be session
        // recording events in the `events_plugin_ingestion` topic for a while
        // so we need to still handle these events with the current consumer.
        const token = uuidv4()
        const teamId = await createTeam(organizationId, undefined, token)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture({
            teamId: null,
            distinctId,
            uuid,
            event: '$snapshot',
            properties: {
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            },
            token,
            sentAt: new Date(),
            eventTime: new Date(),
            now: new Date(),
            topic: 'session_recording_events',
        })

        await waitForExpect(async () => {
            const events = await fetchSessionRecordingsEvents(teamId)
            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')
        })
    },
    20000
)

test.concurrent(`recording events not ingested to ClickHouse if team is opted out`, async () => {
    // NOTE: to have something we can assert on in the positive to ensure that
    // we had tried to ingest the recording for the team with the opted out
    // session recording status, we create a team that is opted in and then
    // ingest a recording for that team. We then create a team that is opted in
    // and ingest a recording for that team. We then assert that the recording
    // for the team that is opted in was ingested and the recording for the team
    // that is opted out was not ingested.
    const tokenOptedOut = uuidv4()
    const teamOptedOutId = await createTeam(organizationId, undefined, tokenOptedOut, false)
    const uuidOptedOut = new UUIDT().toString()

    await capture({
        teamId: null,
        distinctId: new UUIDT().toString(),
        uuid: uuidOptedOut,
        event: '$snapshot',
        properties: {
            $session_id: '1234abc',
            $snapshot_data: 'yes way',
        },
        token: tokenOptedOut,
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
        topic: 'session_recording_events',
    })

    const tokenOptedIn = uuidv4()
    const teamOptedInId = await createTeam(organizationId, undefined, tokenOptedIn)
    const uuidOptedIn = new UUIDT().toString()

    await capture({
        teamId: null,
        distinctId: new UUIDT().toString(),
        uuid: uuidOptedIn,
        event: '$snapshot',
        properties: {
            $session_id: '1234abc',
            $snapshot_data: 'yes way',
        },
        token: tokenOptedIn,
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
        topic: 'session_recording_events',
    })

    await waitForExpect(async () => {
        const events = await fetchSessionRecordingsEvents(teamOptedInId)
        expect(events.length).toBe(1)
    })

    // NOTE: we're assuming that we have a single partition for the Kafka topic,
    // and that the consumer produces messages in the order they are consumed.
    // TODO: add some side-effect we can assert on rather than relying on the
    // partitioning / ordering setup e.g. an ingestion warning.
    const events = await fetchSessionRecordingsEvents(teamOptedOutId, uuidOptedOut)
    expect(events.length).toBe(0)
})

test.concurrent(
    `snapshot captured, processed, ingested via session_recording_events topic same as events_plugin_ingestion`,
    async () => {
        // We are moving from using `events_plugin_ingestion` as the kafka topic
        // for session recordings, so we want to make sure that they still work
        // when sent through `session_recording_events`.
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$snapshot',
            properties: {
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            },
        })

        await waitForExpect(async () => {
            const events = await fetchSessionRecordingsEvents(teamId)
            expect(events.length).toBe(1)
            return events
        })

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$snapshot',
            properties: {
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            },
            token: null,
            sentAt: new Date(),
            eventTime: new Date(),
            now: new Date(),
            topic: 'session_recording_events',
        })

        const eventsThroughNewTopic = await waitForExpect(async () => {
            const eventsThroughNewTopic = await fetchSessionRecordingsEvents(teamId)
            expect(eventsThroughNewTopic.length).toBe(2)
            return eventsThroughNewTopic
        })

        expect(eventsThroughNewTopic[0]).toEqual({
            ...eventsThroughNewTopic[1],
            _offset: expect.any(Number),
            _timestamp: expect.any(String),
            created_at: expect.any(String),
            timestamp: expect.any(String),
        })
    },
    20000
)

test.concurrent(
    `ingests $performance_event via events_plugin_ingestion topic`,
    async () => {
        // We have switched from pushing the `events_plugin_ingestion` to
        // pushing to `session_recording_events`. There will still be
        // `$performance_event` events in the `events_plugin_ingestion` topic
        // for a while so we need to still handle these events with the current
        // consumer.
        // TODO: we push recording events that we get from
        // `events_plugin_ingestion` to `session_recording_events`. We should be
        // able to remove this push and this test once we know there are no more
        // recording events in `events_plugin_ingestion`.
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()
        const sessionId = new UUIDT().toString()
        const now = new Date()

        const properties = {
            // Taken from a real event from the JS
            '0': 'resource',
            '1': now.getTime(),
            '2': 'http://localhost:8000/api/projects/1/session_recordings',
            '3': 10737.89999999106,
            '4': 0,
            '5': 0,
            '6': 0,
            '7': 10737.89999999106,
            '8': 10737.89999999106,
            '9': 10737.89999999106,
            '10': 10737.89999999106,
            '11': 0,
            '12': 10737.89999999106,
            '13': 10745.09999999404,
            '14': 11121.70000000298,
            '15': 11122.20000000298,
            '16': 73374,
            '17': 1767,
            '18': 'fetch',
            '19': 'http/1.1',
            '20': 'non-blocking',
            '22': 2067,
            '39': 384.30000001192093,
            '40': now.getTime() + 1000,
            token: 'phc_234',
            $session_id: sessionId,
            $window_id: '1853a793ad424a5-017f7473b057f1-17525635-384000-1853a793ad524dc',
            distinct_id: '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
            $current_url: 'http://localhost:8000/recordings/recent',
        }

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$performance_event',
            properties,
            token: null,
            sentAt: now,
            eventTime: now,
            now,
        })

        const events = await waitForExpect(async () => {
            const events = await fetchPerformanceEvents(teamId)
            expect(events.length).toBe(1)
            return events
        })

        expect(events[0]).toEqual({
            session_id: sessionId,
            _offset: expect.any(Number),
            _partition: expect.any(Number),
            _timestamp: expect.any(String),
            connect_end: 10737.89999999106,
            connect_start: 10737.89999999106,
            current_url: 'http://localhost:8000/recordings/recent',
            decoded_body_size: 73374,
            distinct_id: distinctId,
            dom_complete: 0,
            dom_content_loaded_event: 0,
            dom_interactive: 0,
            domain_lookup_end: 10737.89999999106,
            domain_lookup_start: 10737.89999999106,
            duration: 384.30000001192093,
            encoded_body_size: 1767,
            entry_type: 'resource',
            fetch_start: 10737.89999999106,
            initiator_type: 'fetch',
            largest_contentful_paint_element: '',
            largest_contentful_paint_id: '',
            largest_contentful_paint_load_time: 0,
            largest_contentful_paint_render_time: 0,
            largest_contentful_paint_size: 0,
            largest_contentful_paint_url: '',
            load_event_end: 0,
            load_event_start: 0,
            name: 'http://localhost:8000/api/projects/1/session_recordings',
            navigation_type: '',
            next_hop_protocol: 'http/1.1',
            pageview_id: '',
            redirect_count: 0,
            redirect_end: 0,
            redirect_start: 0,
            render_blocking_status: 'non-blocking',
            request_start: 10745.09999999404,
            response_end: 11122.20000000298,
            response_start: 11121.70000000298,
            response_status: 0,
            secure_connection_start: 0,
            start_time: 10737.89999999106,
            team_id: teamId,
            time_origin: expect.any(String),
            timestamp: expect.any(String),
            transfer_size: 2067,
            unload_event_end: 0,
            unload_event_start: 0,
            uuid: uuid,
            window_id: '1853a793ad424a5-017f7473b057f1-17525635-384000-1853a793ad524dc',
            worker_start: 0,
        })
    },
    20000
)

test.concurrent(
    `ingests $performance_event via session_recording_events topic same as events_plugin_ingestion`,
    async () => {
        // We have switched from pushing the `events_plugin_ingestion` to
        // pushing to `session_recording_events`. so we want to make sure that
        // they still work when sent through `session_recording_events` topic.
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()
        const now = new Date()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$performance_event',
            properties: {
                '0': 'resource',
                '1': now.getTime(),
                '40': now.getTime() + 1000,
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            },
        })

        await waitForExpect(async () => {
            const events = await fetchPerformanceEvents(teamId)
            expect(events.length).toBe(1)
            return events
        })

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$performance_event',
            properties: {
                '0': 'resource',
                '1': now.getTime(),
                '40': now.getTime() + 1000,
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            },
            token: null,
            sentAt: now,
            eventTime: now,
            now,
            topic: 'session_recording_events',
        })

        const eventsThroughNewTopic = await waitForExpect(async () => {
            const eventsThroughNewTopic = await fetchPerformanceEvents(teamId)
            expect(eventsThroughNewTopic.length).toBe(2)
            return eventsThroughNewTopic
        })

        expect(eventsThroughNewTopic[0]).toEqual({
            ...eventsThroughNewTopic[1],
            _offset: expect.any(Number),
            _timestamp: expect.any(String),
            timestamp: expect.any(String),
        })
    },
    20000
)

test.concurrent(`liveness check endpoint works`, async () => {
    await waitForExpect(async () => {
        const response = await fetch('http://localhost:6738/_health')
        expect(response.status).toBe(200)

        const body = await response.json()
        expect(body).toEqual(
            expect.objectContaining({
                checks: expect.objectContaining({ 'session-recordings': 'ok' }),
            })
        )
    })
})

test.concurrent(
    `consumer handles empty messages`,
    async () => {
        const key = uuidv4()

        await produce({ topic: 'session_recording_events', message: null, key })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    },
    20000
)

test.concurrent('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: { topic: 'session_recording_events', partition: '0', groupId: 'session-recordings' },
    })

    await produce({ topic: 'session_recording_events', message: Buffer.from(''), key: '' })

    await waitForExpect(async () => {
        const metricAfter = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: { topic: 'session_recording_events', partition: '0', groupId: 'session-recordings' },
        })
        expect(metricAfter).toBeGreaterThan(metricBefore)
        expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
        expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
    }, 10_000)
})

test.concurrent(`handles invalid JSON`, async () => {
    const key = uuidv4()

    await produce({ topic: 'session_recording_events', message: Buffer.from('invalid json'), key })

    await waitForExpect(() => {
        const messages = dlq.filter((message) => message.key?.toString() === key)
        expect(messages.length).toBe(1)
    })
})

test.concurrent(`handles message with no token or with token and no associated team_id`, async () => {
    // NOTE: Here we are relying on the topic only having a single partition,
    // which ensures that if the last message we send is in ClickHouse, then
    // that should mean that the previous messages have already been processed.
    // We need to do this because we do not have a way to check the logs or
    // metrics in an easy way.
    //
    // We expect that no token and invalid tokens should not go to the DLQ
    const token = uuidv4()
    const teamId = await createTeam(organizationId, undefined, token)
    const noTokenKey = uuidv4()
    const noAssociatedTeamKey = uuidv4()
    const noTokenUuid = uuidv4()
    const noAssociatedTeamUuid = uuidv4()
    const uuid = uuidv4()

    await produce({
        topic: 'session_recording_events',
        message: Buffer.from(JSON.stringify({ uuid: noTokenUuid, data: JSON.stringify({}) })),
        key: noTokenKey,
    })
    await produce({
        topic: 'session_recording_events',
        message: Buffer.from(
            JSON.stringify({ uuid: noAssociatedTeamUuid, token: 'no associated team', data: JSON.stringify({}) })
        ),
        key: noAssociatedTeamKey,
    })

    await capture({
        teamId: teamId,
        distinctId: new UUIDT().toString(),
        uuid: uuid,
        event: '$snapshot',
        properties: {
            $session_id: '1234abc',
            $snapshot_data: 'yes way',
        },
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
        topic: 'session_recording_events',
    })

    await waitForExpect(async () => {
        const events = await fetchSessionRecordingsEvents(teamId, uuid)
        expect(events.length).toBe(1)
    })

    // These shouldn't have been DLQ'd
    expect(dlq.filter((message) => message.key?.toString() === noTokenKey).length).toBe(0)
    expect(dlq.filter((message) => message.key?.toString() === noAssociatedTeamKey).length).toBe(0)

    // And they shouldn't have been ingested into ClickHouse
    expect((await fetchSessionRecordingsEvents(teamId, noTokenUuid)).length).toBe(0)
    expect((await fetchSessionRecordingsEvents(teamId, noAssociatedTeamUuid)).length).toBe(0)
})

// TODO: implement schema validation and add a test.
