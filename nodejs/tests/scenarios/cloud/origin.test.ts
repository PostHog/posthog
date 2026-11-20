import { execFileSync } from 'child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'

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
            const origin = githubOrigin(api, repo)

            expect(origin.head()).toBe(head)
            expect(origin.cardAt(head, 'committed')).toBe('id: committed\n')
            expect(() => origin.cardAt(head, 'untracked')).toThrow(/untracked\.yaml/)
        } finally {
            rmSync(repo, { recursive: true, force: true })
        }
    })
})
