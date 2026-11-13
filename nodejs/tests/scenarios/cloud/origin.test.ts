import http from 'http'
import { AddressInfo } from 'net'

import { githubOrigin } from './origin'

const PUBLISHED = 'c0ffee0000000000000000000000000000000000'

describe('githubOrigin', () => {
    let server: http.Server
    let api: string

    beforeAll(async () => {
        server = http.createServer((request, response) => {
            if (!request.headers['user-agent']) {
                response.writeHead(403).end('Request forbidden by administrative rules.')
            } else if (request.url === `/repos/PostHog/posthog/commits/${PUBLISHED}`) {
                response.writeHead(200, { 'content-type': 'application/json' }).end('{}')
            } else {
                response.writeHead(422, { 'content-type': 'application/json' }).end('{}')
            }
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        api = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())))

    it.each([
        [PUBLISHED, true],
        ['0'.repeat(40), false],
    ])('answers whether commit %s is on GitHub', async (commit, published) => {
        await expect(githubOrigin(api).published(commit)).resolves.toBe(published)
    })
})
