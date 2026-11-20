import http from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

import { captureEmit, devTarget } from './target'

describe('captureEmit', () => {
    it.each([
        [200, { accepted: true }],
        [400, 'capture refused run-a-1 with 400'],
    ])('offers a unit to capture with its run id, and reads capture answering %i', async (status, outcome) => {
        const seen: { url?: string; authorization?: string; body: unknown }[] = []
        const server = http.createServer((req, res) => {
            let text = ''
            req.on('data', (chunk) => (text += chunk))
            req.on('end', () => {
                seen.push({ url: req.url, authorization: req.headers.authorization, body: parseJSON(text) })
                res.writeHead(status, { 'content-type': 'application/json' }).end(
                    JSON.stringify({ status: status === 200 ? 'Ok' : 'Error' })
                )
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
        const config = {
            host: url,
            capture: url,
            offers: { teamId: 1, token: 'phc_test', workflowId: 'flow-1' },
            receiptsTeamId: 2,
            key: 'phx_test',
        }
        try {
            const emit = captureEmit(config, 'run-a')

            const offered = emit({ unitId: 'run-a-1', teamId: 1, flowId: 'flow-1' }, 'scenario_offer', {
                unit_id: 'run-a-1',
            })
            expect(await offered.catch((error: Error) => error.message)).toEqual(outcome)
            expect(seen).toEqual([
                {
                    url: '/i/v0/e/',
                    authorization: undefined,
                    body: {
                        api_key: 'phc_test',
                        event: 'scenario_offer',
                        distinct_id: 'run-a-1',
                        properties: { unit_id: 'run-a-1', run_id: 'run-a' },
                    },
                },
            ])
        } finally {
            await new Promise<void>((done) => server.close(() => done()))
        }
    })

    it('fails at seed, before any offer, when dev does not know the workflow', async () => {
        const server = http.createServer((_req, res) => res.writeHead(404).end('{}'))
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
        const config = {
            host: url,
            capture: url,
            offers: { teamId: 1, token: 'phc_test', workflowId: 'flow-1' },
            receiptsTeamId: 2,
            key: 'phx_test',
        }
        try {
            const run = devTarget(config).open(undefined as never, 'run-a')

            await expect(run.seed(new AbortController().signal)).rejects.toThrow(
                'dev answered the workflow metrics read with 404'
            )
        } finally {
            await new Promise<void>((done) => server.close(() => done()))
        }
    })
})
