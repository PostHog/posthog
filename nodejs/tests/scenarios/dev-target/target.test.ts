import http from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

import type { DevConfig } from './config'
import { captureEmit } from './target'

type Answer = (uuid: string) => { status: number; body: object }

async function fakeCapture(answer: Answer) {
    const seen: { url?: string; headers: http.IncomingHttpHeaders; body: any }[] = []
    const server = http.createServer((req, res) => {
        let text = ''
        req.on('data', (chunk) => (text += chunk))
        req.on('end', () => {
            const body = parseJSON(text)
            seen.push({ url: req.url, headers: req.headers, body })
            const reply = answer(body.batch[0].uuid)
            res.writeHead(reply.status, { 'content-type': 'application/json' }).end(JSON.stringify(reply.body))
        })
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const config: DevConfig = {
        host: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
        offers: { teamId: 1, token: 'phc_test', workflowId: 'flow-1' },
        receiptsTeamId: 2,
        monthlyRuns: 10_000,
        key: 'phx_test',
    }
    return { config, seen, close: () => new Promise<void>((done) => server.close(() => done())) }
}

const stored: Answer = (uuid) => ({ status: 200, body: { results: { [uuid]: { result: 'ok' } } } })
const unit = (n: number) => ({ unitId: `run-a-${n}`, teamId: 1, flowId: 'flow-1' })

describe('captureEmit', () => {
    it.each<[string, Answer, object]>([
        ['stored it', stored, { accepted: true }],
        [
            'dropped it over its quota',
            (uuid) => ({
                status: 200,
                body: { results: { [uuid]: { result: 'drop', details: 'events_over_quota' } } },
            }),
            { accepted: false, status: 200, outcome: 'drop events_over_quota' },
        ],
        [
            'refused the whole request',
            () => ({ status: 402, body: { error: 'quota' } }),
            { accepted: false, status: 402, outcome: '{"error":"quota"}' },
        ],
    ])('offers a unit to capture v1 with its run id, and answers that capture %s', async (_story, answer, outcome) => {
        const capture = await fakeCapture(answer)
        try {
            const emit = captureEmit(capture.config, 'run-a', 10)

            expect(await emit(unit(1), 'scenario_offer', { unit_id: 'run-a-1' })).toEqual(outcome)
            expect(capture.seen).toEqual([
                {
                    url: '/i/v1/analytics/events',
                    headers: expect.objectContaining({
                        authorization: 'Bearer phc_test',
                        'posthog-attempt': '1',
                        'posthog-sdk-info': expect.stringMatching(/^[^/]+\/[^/]+$/),
                        'posthog-request-id': expect.any(String),
                        'posthog-request-timestamp': expect.any(String),
                    }),
                    body: {
                        created_at: expect.any(String),
                        batch: [
                            {
                                event: 'scenario_offer',
                                uuid: expect.any(String),
                                distinct_id: 'run-a-1',
                                timestamp: expect.any(String),
                                properties: { unit_id: 'run-a-1', run_id: 'run-a' },
                            },
                        ],
                    },
                },
            ])
        } finally {
            await capture.close()
        }
    })

    it('throws on a unit past its budget without sending it', async () => {
        const capture = await fakeCapture(stored)
        try {
            const emit = captureEmit(capture.config, 'run-a', 1)
            await emit(unit(1), 'scenario_offer', { unit_id: 'run-a-1' })

            await expect(emit(unit(2), 'scenario_offer', { unit_id: 'run-a-2' })).rejects.toThrow(
                'the run spent its budget of 1 dev units before run-a-2'
            )
            expect(capture.seen).toHaveLength(1)
        } finally {
            await capture.close()
        }
    })
})
