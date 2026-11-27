import { execFileSync } from 'child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
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

const gitIn = (cwd: string, ...args: string[]): string =>
    execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()

const commitIn = (repo: string, message: string, atS: number): void => {
    writeFileSync(path.join(repo, 'story.txt'), `${message}\n`)
    gitIn(repo, 'add', '-f', '--', 'story.txt')
    execFileSync(
        'git',
        [
            '-c',
            'user.name=Scenario',
            '-c',
            'user.email=scenario@example.com',
            '-c',
            'commit.gpgsign=false',
            'commit',
            '-q',
            '-m',
            message,
        ],
        { cwd: repo, env: { ...process.env, GIT_AUTHOR_DATE: `@${atS} +0000`, GIT_COMMITTER_DATE: `@${atS} +0000` } }
    )
}

describe('githubOrigin', () => {
    let server: http.Server
    let api: string
    let answers: Answer[]
    let authorizations: (string | undefined)[]
    let repos: string
    let remote: string
    let checkout: string
    let mirrorHome: string

    const checkoutState = (): string =>
        [
            gitIn(checkout, 'for-each-ref'),
            gitIn(checkout, 'config', '--get', 'core.bare'),
            readFileSync(path.join(checkout, '.git', 'shallow'), 'utf8'),
        ].join('\n')

    const viaApi = (io: OriginIo): ReturnType<typeof githubOrigin> =>
        githubOrigin(io, api, checkout, `file://${repos}/missing.git`)

    const scripted = (): { io: OriginIo; waits: number[]; warned: string[] } => {
        const waits: number[] = []
        const warned: string[] = []
        return {
            io: {
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

    beforeAll(() => {
        repos = mkdtempSync(path.join(os.tmpdir(), 'scenario-origin-git-'))
        remote = path.join(repos, 'posthog.git')
        checkout = path.join(repos, 'checkout')
        mkdirSync(remote)
        mkdirSync(checkout)
        gitIn(remote, 'init', '-q', '-b', 'master')
        gitIn(remote, 'config', 'uploadpack.allowFilter', 'true')
        commitIn(remote, 'root', NOW_S - 20 * 24 * 3600)
        commitIn(remote, 'merged', NOW_S - 7200)
        gitIn(remote, 'branch', 'pinned')
        gitIn(remote, 'switch', '-q', '-c', 'side')
        commitIn(remote, 'only on a branch', NOW_S - 3600)
        gitIn(remote, 'switch', '-q', 'master')
        commitIn(remote, 'merged with an older date', NOW_S - 10 * 24 * 3600)
        commitIn(remote, 'merged an hour ago', NOW_S - 3600)
        commitIn(remote, 'merged half an hour ago', NOW_S - 1800)
        gitIn(remote, 'branch', 'merged')
        commitIn(remote, 'merged later', NOW_S)
        gitIn(checkout, 'init', '-q')
        gitIn(
            checkout,
            'fetch',
            '-q',
            '--depth',
            '1',
            `file://${remote}`,
            '+refs/heads/pinned:refs/heads/pinned',
            '+refs/heads/side:refs/heads/side',
            '+refs/heads/merged:refs/heads/merged'
        )
        const mirror = path.join(repos, 'mirror.git')
        gitIn(repos, 'clone', '-q', '--bare', remote, mirror)
        gitIn(mirror, 'update-ref', 'refs/heads/master', 'refs/heads/side')
        mirrorHome = path.join(repos, 'home')
        mkdirSync(mirrorHome)
        writeFileSync(path.join(mirrorHome, '.gitconfig'), `[url "file://${mirror}"]\n\tinsteadOf = file://${remote}\n`)
    })

    afterAll(() => {
        rmSync(repos, { recursive: true, force: true })
        return new Promise<void>((resolve) => server.close(() => resolve()))
    })

    it.each([
        ['answers from git, without asking GitHub, that a commit master holds is', 'merged', [], true, 0],
        ['asks GitHub whether a commit behind an older-dated master commit is', 'pinned', [{ status: 200 }], true, 1],
        ['asks GitHub whether a commit git finds only on a branch is', 'side', [], false, 1],
    ])(
        '%s on master, and leaves the shallow checkout as it was',
        async (_story, branch, scriptedAnswers, onMaster, requests) => {
            const commit = gitIn(checkout, 'rev-parse', branch)
            const before = checkoutState()
            answers = [...scriptedAnswers]

            await expect(githubOrigin(scripted().io, api, checkout, `file://${remote}`).onMaster(commit)).resolves.toBe(
                onMaster
            )
            expect({ requests: authorizations.length, state: checkoutState() }).toEqual({ requests, state: before })
        }
    )

    it.each([
        ['GIT_DIR names the checkout', (): NodeJS.ProcessEnv => ({ GIT_DIR: path.join(checkout, '.git') })],
        [
            "the caller's git config rewrites the remote to a mirror whose master holds a branch commit",
            (): NodeJS.ProcessEnv => ({ HOME: mirrorHome }),
        ],
    ])('asks GitHub, and leaves the checkout as it was, when %s', async (_story, inherited) => {
        const commit = gitIn(checkout, 'rev-parse', 'side')
        const before = checkoutState()
        const env = inherited()
        const saved = Object.fromEntries(Object.keys(env).map((name) => [name, process.env[name]]))
        Object.assign(process.env, env)
        try {
            await expect(githubOrigin(scripted().io, api, checkout, `file://${remote}`).onMaster(commit)).resolves.toBe(
                false
            )
        } finally {
            Object.entries(saved).forEach(([name, value]) =>
                value === undefined ? delete process.env[name] : (process.env[name] = value)
            )
        }
        expect({ requests: authorizations.length, state: checkoutState() }).toEqual({ requests: 1, state: before })
    })

    it("asks GitHub's API when git cannot reach the remote", async () => {
        answers = [{ status: 200 }]
        const { io, warned } = scripted()
        const commit = gitIn(checkout, 'rev-parse', 'side')

        await expect(viaApi(io).onMaster(commit)).resolves.toBe(true)
        expect({ requests: authorizations.length, warned: warned.join('\n') }).toEqual({
            requests: 1,
            warned: expect.stringContaining(`Git could not confirm that commit ${commit} is on master`),
        })
    })

    it.each([
        ['a'.repeat(40), 'is master', true],
        ['b'.repeat(40), 'is behind master', true],
        ['c'.repeat(40), 'is only on a branch ahead of master', false],
        ['d'.repeat(40), 'is only on a pull request that diverged from master', false],
        ['0'.repeat(40), 'GitHub does not know', false],
    ])('answers whether commit %s, which %s, is on master', async (commit, _, onMaster) => {
        await expect(viaApi(scripted().io).onMaster(commit)).resolves.toBe(onMaster)
    })

    it.each([
        ['a reset 5 s away', 403, RATE_LIMITED.headers, 'Request refused.', 5_000],
        [
            'a reset an hour away',
            403,
            { 'x-ratelimit-remaining': '0', 'x-ratelimit-reset': String(NOW_S + 3600) },
            'Request refused.',
            60_000,
        ],
        ['a retry-after of 3 s', 403, { 'retry-after': '3' }, 'Request refused.', 3_000],
        [
            'quota left but a secondary limit hit',
            403,
            { 'x-ratelimit-remaining': '12', 'x-ratelimit-reset': String(NOW_S + 5) },
            'You have exceeded a secondary rate limit.',
            60_000,
        ],
        ['no rate-limit headers', 429, {}, 'Request refused.', 60_000],
    ])(
        'retries once after a rate-limited answer with %s, waiting at most a minute',
        async (_story, status, headers, message, waited) => {
            answers = [{ status, headers, message }, { status: 200 }]
            const { io, waits, warned } = scripted()

            await expect(viaApi(io).onMaster(COMMIT)).resolves.toBe(true)
            expect({ requests: authorizations.length, waits, warned: warned.join('\n') }).toEqual({
                requests: 2,
                waits: [waited],
                warned: expect.stringContaining(
                    `GitHub answered ${status} comparing commit ${COMMIT} with master: ${message}`
                ),
            })
        }
    )

    it('sends no retry until the wait before it ends', async () => {
        answers = [RATE_LIMITED, { status: 200 }]
        const { io } = scripted()
        const interrupted = new Error('Interrupted while waiting to retry.')

        await expect(viaApi({ ...io, sleep: () => Promise.reject(interrupted) }).onMaster(COMMIT)).rejects.toBe(
            interrupted
        )
        expect(authorizations).toHaveLength(1)
    })

    it.each([
        [
            'refuses the retry too',
            [RATE_LIMITED, RATE_LIMITED],
            `GitHub answered 403 comparing commit ${COMMIT} with master: API rate limit exceeded for 192.0.2.1. (x-ratelimit-remaining: 0, x-ratelimit-reset: ${NOW_S + 5})`,
            [5_000],
            2,
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
            1,
        ],
    ])(
        "throws with GitHub's message and rate-limit headers when GitHub %s",
        async (_story, refusals, error, waited, requests) => {
            answers = [...refusals]
            const { io, waits } = scripted()

            await expect(viaApi(io).onMaster(COMMIT)).rejects.toThrow(error)
            expect({ requests: authorizations.length, waits }).toEqual({ requests, waits: waited })
        }
    )

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
