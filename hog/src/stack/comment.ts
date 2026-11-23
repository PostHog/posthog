import { z } from 'zod'

import { EXIT_USAGE, HogError } from '@/core/errors'
import { parseJson } from '@/core/json'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'
import { sendRequest } from '@/posthog/api'
import { MAX_PAGES } from '@/posthog/pagination'

import type { ResolvedStack } from './config'

const Ci = z.object({
    GITHUB_REPOSITORY: z.string().regex(/^[\w.-]+\/[\w.-]+$/),
    GITHUB_EVENT_PATH: z.string().min(1),
    GITHUB_TOKEN: z.string().min(1),
    GITHUB_SERVER_URL: z.url({ protocol: /^https$/ }).default('https://github.com'),
})
const Event = z.object({ pull_request: z.object({ number: z.int().positive() }) })
const Comment = z.object({ id: z.int().positive(), body: z.string(), user: z.object({ login: z.string() }) })

export async function commentOnPullRequest(
    runtime: Runtime,
    stack: ResolvedStack,
    project: string,
    block: string
): Promise<void> {
    const config = Ci.safeParse(runtime.env).data
    const hint = 'Use --comment in a GitHub pull request job with GITHUB_TOKEN and pull-requests: write.'
    if (!config) {
        throw new HogError(
            'pull_request_required',
            'GitHub pull request details or its token are missing.',
            hint,
            EXIT_USAGE
        )
    }
    const text = await runtime.readFile(config.GITHUB_EVENT_PATH).catch(() => '')
    const {
        pull_request: { number },
    } = parseJson(text, Event, {
        code: 'pull_request_required',
        context: 'Could not read the pull request number.',
        hint,
        exitCode: EXIT_USAGE,
    })
    const marker = `<!-- hog-stack-diff ${project} ${stack.name} ${stack.env ?? '-'} -->`
    const longest = block.match(/`+/g)?.reduce((length, run) => Math.max(length, run.length), 0) ?? 0
    const fence = '`'.repeat(Math.max(3, longest + 1))
    const body = `${marker}\n${fence}text\n${block}\n${fence}`
    const server = new URL(config.GITHUB_SERVER_URL)
    const api = server.origin === 'https://github.com' ? 'https://api.github.com' : `${server.origin}/api/v3`
    const base = `${api}/repos/${config.GITHUB_REPOSITORY}/issues/`
    const request = async (
        path: string,
        method: 'GET' | 'PATCH' | 'POST',
        contents?: { body: string }
    ): Promise<unknown> => {
        const answer = await sendRequest(runtime.fetch, new URL(base + path), {
            method,
            token: config.GITHUB_TOKEN,
            body: contents,
            timeoutMs: 15_000,
        })
        if (!answer.ok) {
            throw new HogError(
                'pull_request_comment_failed',
                `GitHub could not ${method === 'GET' ? 'read the comments' : 'save the diff comment'} (HTTP ${answer.status}).`,
                hint
            )
        }
        return answer.json
    }
    const path = `${number}/comments`
    for (let page = 1; page <= MAX_PAGES; page++) {
        const comments = parseOrThrow(z.array(Comment), await request(`${path}?per_page=100&page=${page}`, 'GET'), {
            code: 'pull_request_comment_failed',
            context: 'Could not read the comments from GitHub.',
            hint,
        })
        const previous = comments.find(
            (comment) => comment.user.login === 'github-actions[bot]' && comment.body.startsWith(`${marker}\n`)
        )
        if (previous) {
            await request(`comments/${previous.id}`, 'PATCH', { body })
            return
        }
        if (comments.length < 100) {
            await request(path, 'POST', { body })
            return
        }
    }
    throw new HogError(
        'pull_request_comment_limit',
        'This pull request has more comments than hog can search.',
        'Run hog diff without --comment to read the changes.'
    )
}
