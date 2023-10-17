import fetch from 'node-fetch'
import { v4 as uuidv4 } from 'uuid'

import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../src/config/kafka-topics'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam, fetchSessionReplayEvents, getMetric } from './api'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

let organizationId: string

beforeAll(async () => {
    organizationId = await createOrganization()
})

test.skip(`snapshot captured, processed, ingested`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()
    const sessionId = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid,
        event: '$snapshot_items',
        properties: {
            $session_id: sessionId,
            $window_id: 'abc1234',
            $snapshot_items: ['yes way'],
        },
    })

    const events = await waitForExpect(async () => {
        const events = await fetchSessionReplayEvents(teamId, sessionId)
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
        session_id: sessionId,
        snapshot_data: 'yes way',
        team_id: teamId,
        timestamp: expect.any(String),
        timestamps_summary: [],
        urls: [],
        uuid: uuid,
        window_id: 'abc1234',
    })
}, 20000)

test.skip(`snapshot captured, processed, ingested with no team_id set`, async () => {
    const token = uuidv4()
    const teamId = await createTeam(organizationId, undefined, token)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    await capture({
        teamId: null,
        distinctId,
        uuid,
        event: '$snapshot_items',
        properties: {
            $session_id: '1234abc',
            $snapshot_items: ['yes way'],
        },
        token,
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
    })

    await waitForExpect(async () => {
        const events = await fetchSessionReplayEvents(teamId)
        expect(events.length).toBe(1)
    })
}, 20000)

test.skip(`recording events not ingested to ClickHouse if team is opted out`, async () => {
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
        event: '$snapshot_items',
        properties: {
            $session_id: '1234abc',
            $snapshot_items: ['yes way'],
        },
        token: tokenOptedOut,
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
    })

    const tokenOptedIn = uuidv4()
    const teamOptedInId = await createTeam(organizationId, undefined, tokenOptedIn)
    const uuidOptedIn = new UUIDT().toString()

    await capture({
        teamId: null,
        distinctId: new UUIDT().toString(),
        uuid: uuidOptedIn,
        event: '$snapshot_items',
        properties: {
            $session_id: '1234abc',
            $snapshot_items: ['yes way'],
        },
        token: tokenOptedIn,
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
    })

    await waitForExpect(async () => {
        const events = await fetchSessionReplayEvents(teamOptedInId)
        expect(events.length).toBe(1)
    })

    // NOTE: we're assuming that we have a single partition for the Kafka topic,
    // and that the consumer produceAndFlushs messages in the order they are consumed.
    // TODO: add some side-effect we can assert on rather than relying on the
    // partitioning / ordering setup e.g. an ingestion warning.
    const events = await fetchSessionReplayEvents(teamOptedOutId)
    expect(events.length).toBe(0)
})

test.concurrent(`liveness check endpoint works`, async () => {
    await waitForExpect(async () => {
        const response = await fetch('http://localhost:6738/_health')
        expect(response.status).toBe(200)

        const body = await response.json()
        expect(body).toEqual(
            expect.objectContaining({
                checks: expect.objectContaining({ 'session-recordings-blob': 'ok' }),
            })
        )
    })
})

test.skip('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: {
            topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
            partition: '0',
            groupId: 'session-recordings-blob',
        },
    })

    await produce({ topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS, message: Buffer.from(''), key: '' })

    await waitForExpect(async () => {
        const metricAfter = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: {
                topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
                partition: '0',
                groupId: 'session-recordings-blob',
            },
        })
        expect(metricAfter).toBeGreaterThan(metricBefore)
        expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
        expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
    }, 10_000)
})

function makeSessionMessage(
    teamId: number,
    sessionId: string,
    uuid?: string
): {
    teamId: number | null
    distinctId: string
    uuid: string
    event: string
    properties?: object | undefined
    token?: string | null | undefined
    sentAt?: Date | undefined
    eventTime?: Date | undefined
    now?: Date | undefined
    topic?: string | undefined
    $set?: object | undefined
    $set_once?: object | undefined
} {
    return {
        teamId: teamId,
        distinctId: new UUIDT().toString(),
        uuid: uuid || new UUIDT().toString(),
        event: '$snapshot_items',
        properties: {
            $session_id: sessionId,
            $snapshot_items: ['yes way'],
        },
        sentAt: new Date(),
        eventTime: new Date(),
        now: new Date(),
        topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    }
}

// TODO we can't query for replay events by UUID
test.skip(`handles message with no token or with token and no associated team_id`, async () => {
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

    await produce({
        topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
        message: Buffer.from(JSON.stringify({ uuid: noTokenUuid, data: JSON.stringify({}) })),
        key: noTokenKey,
    })
    await produce({
        topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
        message: Buffer.from(
            JSON.stringify({ uuid: noAssociatedTeamUuid, token: 'no associated team', data: JSON.stringify({}) })
        ),
        key: noAssociatedTeamKey,
    })

    await capture(makeSessionMessage(teamId, 'should be ingested'))

    await waitForExpect(async () => {
        const events = await fetchSessionReplayEvents(teamId, 'should be ingested')
        expect(events.length).toBe(1)
    })

    // And they shouldn't have been ingested into ClickHouse
    expect((await fetchSessionReplayEvents(teamId, noTokenUuid)).length).toBe(0)
    expect((await fetchSessionReplayEvents(teamId, noAssociatedTeamUuid)).length).toBe(0)
})

// TODO: implement schema validation and add a test.
