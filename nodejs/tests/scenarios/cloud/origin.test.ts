import { execFileSync } from 'child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

import { OriginIo, githubOrigin } from './origin'

const COMPARED: Record<string, string> = {
    ['a'.repeat(40)]: 'identical',
    ['b'.repeat(40)]: 'behind',
    ['c'.repeat(40)]: 'ahead',
    ['d'.repeat(40)]: 'diverged',
}

type Answer = { status: number; headers?: Record<string, string>; message?: string }

const NOW_S = 1_767_225_600
const COMMIT = 'a'.repeat(40)
const RATE_LIMITED: Answer = {
    status: 403,
    headers: { 'x-ratelimit-remaining': '0', 'x-ratelimit-reset': String(NOW_S + 5) },
    message: 'API rate limit exceeded for 192.0.2.1.',
}

describe('githubOrigin', () => {
    let server: http.Server
    let api: string
    let answers: Answer[]
    let authorizations: (string | undefined)[]

    const scripted = (env: NodeJS.ProcessEnv = {}): { io: OriginIo; waits: number[]; warned: string[] } => {
        const waits: number[] = []
        const warned: string[] = []
        return {
            io: {
                env,
                now: () => new Date(NOW_S * 1000),
                sleep: (ms) => {
                    waits.push(ms)
                    return Promise.resolve()
                },
                warn: (line) => warned.push(line),
            },
            waits,
            warned,
        }
    }

    beforeEach(() => {
        answers = []
        authorizations = []
    })

    beforeAll(async () => {
        server = http.createServer((request, response) => {
            authorizations.push(request.headers.authorization)
            const commit = /^\/repos\/PostHog\/posthog\/compare\/master\.\.\.([0-9a-f]{40})$/.exec(
                request.url ?? ''
            )?.[1]
            const answer = commit && request.headers['user-agent'] ? answers.shift() : undefined
            if (answer) {
                response
                    .writeHead(answer.status, { 'content-type': 'application/json', ...answer.headers })
                    .end(JSON.stringify(answer.status === 200 ? { status: 'identical' } : { message: answer.message }))
                return
            }
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
        await expect(githubOrigin(scripted().io, api).onMaster(commit)).resolves.toBe(onMaster)
    })

    it.each([
        ['a reset 5 s away', 403, RATE_LIMITED.headers, 5_000],
        [
            'a reset an hour away',
            403,
            { 'x-ratelimit-remaining': '0', 'x-ratelimit-reset': String(NOW_S + 3600) },
            60_000,
        ],
        ['a retry-after of 3 s', 403, { 'retry-after': '3' }, 3_000],
        [
            'quota left but a secondary limit hit',
            403,
            { 'x-ratelimit-remaining': '12', 'x-ratelimit-reset': String(NOW_S + 5) },
            60_000,
        ],
        ['no rate-limit headers', 429, {}, 60_000],
    ])(
        'retries once after a rate-limited answer with %s, waiting at most a minute',
        async (_story, status, headers, waited) => {
            answers = [{ ...RATE_LIMITED, status, headers }, { status: 200 }]
            const { io, waits, warned } = scripted()

            await expect(githubOrigin(io, api).onMaster(COMMIT)).resolves.toBe(true)
            expect({ waits, warned: warned.join('\n') }).toEqual({
                waits: [waited],
                warned: expect.stringContaining('API rate limit exceeded for 192.0.2.1.'),
            })
        }
    )

    it.each([
        [
            'refuses the retry too',
            [RATE_LIMITED, RATE_LIMITED],
            `GitHub answered 403 comparing commit ${COMMIT} with master: API rate limit exceeded for 192.0.2.1. (x-ratelimit-remaining: 0, x-ratelimit-reset: ${NOW_S + 5})`,
            [5_000],
        ],
        [
            'refuses for a reason other than a rate limit',
            [
                {
                    status: 403,
                    headers: { 'x-ratelimit-remaining': '4999' },
                    message: 'Resource not accessible by integration',
                },
            ],
            `GitHub answered 403 comparing commit ${COMMIT} with master: Resource not accessible by integration (x-ratelimit-remaining: 4999)`,
            [],
        ],
    ])(
        "throws with GitHub's message and rate-limit headers when GitHub %s",
        async (_story, refusals, error, waited) => {
            answers = [...refusals]
            const { io, waits } = scripted()

            await expect(githubOrigin(io, api).onMaster(COMMIT)).rejects.toThrow(error)
            expect(waits).toEqual(waited)
        }
    )

    it.each([
        ['sends the token the environment sets', { GITHUB_TOKEN: 'example-token' }, 'Bearer example-token'],
        ['sends no authorization without a token', {}, undefined],
        ['sends no authorization with an empty token', { GITHUB_TOKEN: '' }, undefined],
    ])('%s', async (_story, env, authorization) => {
        await githubOrigin(scripted(env).io, api).onMaster(COMMIT)

        expect(authorizations).toEqual([authorization])
    })

    it('reads a card as the commit holds it, never as the working tree holds it', () => {
        const repo = mkdtempSync(path.join(os.tmpdir(), 'scenario-origin-'))
        const cards = path.join(repo, 'nodejs', 'tests', 'scenarios', 'cards')
        const git = (...args: string[]): string => execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
        try {
            mkdirSync(cards, { recursive: true })
            git('init', '-q')
            writeFileSync(path.join(cards, 'committed.yaml'), 'id: committed\n')
            git('add', '.')
            git(
                '-c',
                'user.name=Scenario',
                '-c',
                'user.email=scenario@example.com',
                '-c',
                'commit.gpgsign=false',
                'commit',
                '-q',
                '-m',
                'card'
            )
            const head = git('rev-parse', 'HEAD')
            writeFileSync(path.join(cards, 'committed.yaml'), 'id: edited\n')
            writeFileSync(path.join(cards, 'untracked.yaml'), 'id: untracked\n')
            const origin = githubOrigin(scripted().io, api, repo)

            expect(origin.head()).toBe(head)
            expect(origin.cardAt(head, 'committed')).toBe('id: committed\n')
            expect(() => origin.cardAt(head, 'untracked')).toThrow(/untracked\.yaml/)
        } finally {
            rmSync(repo, { recursive: true, force: true })
        }
    })
})
