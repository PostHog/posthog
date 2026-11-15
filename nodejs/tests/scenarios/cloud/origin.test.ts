import { execFileSync } from 'child_process'
import http from 'http'
import { AddressInfo } from 'net'

import { githubOrigin } from './origin'

const COMPARED: Record<string, string> = {
    ['a'.repeat(40)]: 'identical',
    ['b'.repeat(40)]: 'behind',
    ['c'.repeat(40)]: 'ahead',
    ['d'.repeat(40)]: 'diverged',
}

describe('githubOrigin', () => {
    let server: http.Server
    let api: string

    beforeAll(async () => {
        server = http.createServer((request, response) => {
            const commit = /^\/repos\/PostHog\/posthog\/compare\/master\.\.\.([0-9a-f]{40})$/.exec(
                request.url ?? ''
            )?.[1]
            if (!request.headers['user-agent']) {
                response.writeHead(403).end('Request forbidden by administrative rules.')
            } else if (commit && COMPARED[commit]) {
                response
                    .writeHead(200, { 'content-type': 'application/json' })
                    .end(JSON.stringify({ status: COMPARED[commit] }))
            } else {
                response.writeHead(404, { 'content-type': 'application/json' }).end('{}')
            }
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        api = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())))

    it.each([
        ['a'.repeat(40), 'is master', true],
        ['b'.repeat(40), 'is behind master', true],
        ['c'.repeat(40), 'is only on a branch ahead of master', false],
        ['d'.repeat(40), 'is only on a pull request that diverged from master', false],
        ['0'.repeat(40), 'GitHub does not know', false],
    ])('answers whether commit %s, which %s, is on master', async (commit, _, onMaster) => {
        await expect(githubOrigin(api).onMaster(commit)).resolves.toBe(onMaster)
    })

    it('reads a card as the commit holds it and refuses a card the commit does not hold', () => {
        const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: __dirname, encoding: 'utf8' }).trim()

        expect(githubOrigin(api).cardAt(head, 'cyclotron-scale')).toMatch(/^id: cyclotron-scale$/m)
        expect(() => githubOrigin(api).cardAt(head, 'no-such-card')).toThrow(/no-such-card\.yaml/)
    })
})
