import { execFileSync } from 'child_process'

import { FetchResponse, internalFetch } from '~/common/utils/request'

import { Origin } from './admission'

const REPOSITORY = 'PostHog/posthog'
const REQUEST_TIMEOUT_MS = 10_000
const RETRY_WAIT_CAP_MS = 60_000
const RATE_LIMITED = [403, 429]
const RATE_LIMIT_HEADERS = ['x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after']

export type OriginIo = {
    token?: string
    now(): number
    sleep(ms: number): Promise<void>
    warn(line: string): void
}

const PROCESS_IO: OriginIo = {
    token: process.env.GITHUB_TOKEN || undefined,
    now: () => Date.now(),
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    warn: (line) => process.stderr.write(`${line}\n`),
}

async function refusalOf(response: FetchResponse, commit: string): Promise<string> {
    const { message } = ((await response.json().catch(() => ({}))) ?? {}) as { message?: unknown }
    const limits = RATE_LIMIT_HEADERS.filter((name) => response.headers[name] !== undefined).map(
        (name) => `${name}: ${response.headers[name]}`
    )
    return [
        `GitHub answered ${response.status} comparing commit ${commit} with master`,
        typeof message === 'string' ? `: ${message}` : '',
        limits.length > 0 ? ` (${limits.join(', ')})` : '',
    ].join('')
}

function retryWaitMs(headers: Record<string, string>, now: number): number {
    const retryAfterS = Number(headers['retry-after'])
    const resetS = Number(headers['x-ratelimit-reset'])
    const untilAllowedMs = Number.isFinite(retryAfterS)
        ? retryAfterS * 1000
        : Number.isFinite(resetS)
          ? resetS * 1000 - now
          : RETRY_WAIT_CAP_MS
    return Math.min(Math.max(untilAllowedMs, 0), RETRY_WAIT_CAP_MS)
}

export function githubOrigin(
    api: string = 'https://api.github.com',
    repo: string = __dirname,
    io: OriginIo = PROCESS_IO
): Origin {
    return {
        head: () => execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
        cardAt: (commit, id) =>
            execFileSync('git', ['show', `${commit}:nodejs/tests/scenarios/cards/${id}.yaml`], {
                cwd: repo,
                encoding: 'utf8',
                stdio: ['ignore', 'pipe', 'pipe'],
            }),
        onMaster: async (commit) => {
            const compare = (): Promise<FetchResponse> =>
                internalFetch(`${api}/repos/${REPOSITORY}/compare/master...${commit}`, {
                    headers: {
                        Accept: 'application/vnd.github+json',
                        'User-Agent': 'posthog-scenario-runner',
                        ...(io.token && { Authorization: `Bearer ${io.token}` }),
                    },
                    timeoutMs: REQUEST_TIMEOUT_MS,
                })
            let response = await compare()
            if (RATE_LIMITED.includes(response.status)) {
                const waitMs = retryWaitMs(response.headers, io.now())
                io.warn(`${await refusalOf(response, commit)}. Retrying once in ${Math.ceil(waitMs / 1000)} s.`)
                await io.sleep(waitMs)
                response = await compare()
            }
            if (response.status === 404 || response.status === 422) {
                return false
            }
            if (response.status !== 200) {
                throw new Error(await refusalOf(response, commit))
            }
            const { status } = (await response.json()) as { status?: unknown }
            return status === 'identical' || status === 'behind'
        },
    }
}
