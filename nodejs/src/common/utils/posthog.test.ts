import { Server, createServer } from 'http'
import { AddressInfo } from 'net'
import { gunzipSync } from 'node:zlib'
import { CaptureError } from 'posthog-node'

import { parseJSON } from '~/common/utils/json-parse'
import { countCaptureLosses } from '~/common/utils/posthog'
import { waitForExpect } from '~/tests/helpers/expectations'
import { Team } from '~/types'

const ANALYTICS_ENDPOINT = '/i/v1/analytics/events'
const LOST_EVENTS_METRIC = 'posthog_sdk_capture_events_lost_total'
const TOKEN = 'phc_posthog_client_test'

const captureError = (drops: (string | undefined)[], undelivered: number): CaptureError =>
    new CaptureError({
        endpoint: ANALYTICS_ENDPOINT,
        requestId: 'request-1',
        drops: drops.map((details, index) => ({ uuid: `dropped-${index}`, details })),
        retryExhausted: Array.from({ length: undelivered }, (_, index) => `undelivered-${index}`),
    })

describe('PostHog client', () => {
    it.each([
        ['nothing lost', captureError([], 0), {}],
        [
            'drops grouped by detail beside undelivered events',
            captureError(['event_name_too_long', 'queue full', 'event_name_too_long'], 3),
            { event_name_too_long: 2, 'queue full': 1, undelivered: 3 },
        ],
        ['a drop with no detail', captureError([undefined], 0), { other: 1 }],
        [
            'a detail that is not a plain reason code',
            captureError(['Invalid: <html>502 Bad Gateway</html>', 'x'.repeat(65)], 0),
            { other: 2 },
        ],
    ])('counts %s', (_name, error, expected) => {
        expect(Object.fromEntries(countCaptureLosses(error))).toEqual(expected)
    })

    describe('sending to capture', () => {
        let receiver: Server
        let analytics: typeof import('~/common/utils/posthog')
        let metrics: typeof import('prom-client')
        const requests: { path?: string; authorization?: string; sdkInfo?: string; events: string[] }[] = []
        const team = { uuid: 'team-uuid', organization_id: 'organization-id' } as Team

        beforeAll(async () => {
            receiver = createServer((req, res) => {
                const chunks: Buffer[] = []
                req.on('data', (chunk: Buffer) => chunks.push(chunk))
                req.on('end', () => {
                    const raw = Buffer.concat(chunks)
                    const body = parseJSON(
                        (req.headers['content-encoding'] === 'gzip' ? gunzipSync(raw) : raw).toString('utf8')
                    )
                    const batch: { event: string; uuid: string }[] = body.batch
                    requests.push({
                        path: req.url,
                        authorization: req.headers['authorization'],
                        sdkInfo: req.headers['posthog-sdk-info'] as string | undefined,
                        events: batch.map((event) => event.event),
                    })
                    const overQuota = batch.some((event) => event.event === 'over quota event')
                    const results = Object.fromEntries(
                        batch.map((event) => [
                            event.uuid,
                            event.event === 'dropped event'
                                ? { result: 'drop', details: 'event_name_too_long' }
                                : { result: 'ok' },
                        ])
                    )
                    res.writeHead(overQuota ? 402 : 200, { 'Content-Type': 'application/json' })
                    res.end(JSON.stringify(overQuota ? { error: 'billing_limit_exceeded' } : { results }))
                })
            })
            await new Promise<void>((resolve) => receiver.listen(0, '127.0.0.1', resolve))
            process.env.POSTHOG_API_KEY = TOKEN
            process.env.POSTHOG_HOST_URL = `http://127.0.0.1:${(receiver.address() as AddressInfo).port}`
            process.env.NODE_ENV = 'dev'
            try {
                jest.isolateModules(() => {
                    analytics = jest.requireActual('~/common/utils/posthog')
                    metrics = jest.requireActual('prom-client')
                })
            } finally {
                process.env.NODE_ENV = 'test'
            }
        })

        afterAll(async () => {
            await analytics.shutdown()
            receiver.close()
        })

        const send = async (event: string): Promise<void> => {
            const sent = requests.length
            analytics.captureTeamEvent(team, event)
            analytics.flush()
            await waitForExpect(() => expect(requests).toHaveLength(sent + 1))
        }

        const lostEvents = async (): Promise<Record<string, number>> => {
            const metric = await metrics.register.getSingleMetric(LOST_EVENTS_METRIC)!.get()
            return Object.fromEntries(metric.values.map((v) => [`${v.labels.endpoint} ${v.labels.reason}`, v.value]))
        }

        it('sends on capture v1 and counts only the events capture did not accept', async () => {
            await send('delivered event')
            await send('dropped event')
            await send('over quota event')

            await waitForExpect(async () =>
                expect(await lostEvents()).toEqual({
                    [`${ANALYTICS_ENDPOINT} event_name_too_long`]: 1,
                    [`${ANALYTICS_ENDPOINT} undelivered`]: 1,
                })
            )
            expect(requests).toEqual(
                ['delivered event', 'dropped event', 'over quota event'].map((event) => ({
                    path: ANALYTICS_ENDPOINT,
                    authorization: `Bearer ${TOKEN}`,
                    sdkInfo: expect.stringMatching(/^posthog-node\/6\./),
                    events: [event],
                }))
            )
        })
    })
})
