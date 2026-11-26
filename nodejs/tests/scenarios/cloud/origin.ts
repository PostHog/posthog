import { execFileSync } from 'child_process'

import { FetchResponse, internalFetch } from '~/common/utils/request'

import { Controller, Origin } from './admission'

const REPOSITORY = 'PostHog/posthog'
const REQUEST_TIMEOUT_MS = 10_000
const RETRY_WAIT_CAP_MS = 60_000
const RATE_LIMIT_HEADERS = ['x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after']

export type OriginIo = Pick<Controller, 'env' | 'now' | 'sleep' | 'warn'>

async function messageOf(response: FetchResponse): Promise<string | undefined> {
    const { message } = ((await response.json().catch(() => ({}))) ?? {}) as { message?: unknown }
    return typeof message === 'string' ? message : undefined
}

async function refusalOf(response: FetchResponse, commit: string): Promise<string> {
    const message = await messageOf(response)
    const limits = RATE_LIMIT_HEADERS.filter((name) => response.headers[name] !== undefined).map(
        (name) => `${name}: ${response.headers[name]}`
    )
    return [
        `GitHub answered ${response.status} comparing commit ${commit} with master`,
        message ? `: ${message}` : '',
        limits.length > 0 ? ` (${limits.join(', ')})` : '',
    ].join('')
}

// GitHub also answers 403 for a token that lacks access, and that answer does not change on a retry.
async function isRateLimited(response: FetchResponse): Promise<boolean> {
    if (response.status === 429) {
        return true
    }
    return (
        response.status === 403 &&
        (response.headers['x-ratelimit-remaining'] === '0' ||
            response.headers['retry-after'] !== undefined ||
            /rate limit/i.test((await messageOf(response)) ?? ''))
    )
}

// GitHub's rule: honour retry-after, wait for the reset only when the quota is spent, and otherwise wait a minute.
function retryWaitMs(headers: Record<string, string>, now: Date): number {
    const retryAfterS = Number(headers['retry-after'])
    const resetS = Number(headers['x-ratelimit-reset'])
    const untilAllowedMs = Number.isFinite(retryAfterS)
        ? retryAfterS * 1000
        : headers['x-ratelimit-remaining'] === '0' && Number.isFinite(resetS)
          ? resetS * 1000 - now.getTime()
          : RETRY_WAIT_CAP_MS
    return Math.min(Math.max(untilAllowedMs, 0), RETRY_WAIT_CAP_MS)
}

export function githubOrigin(io: OriginIo, api = 'https://api.github.com', repo = __dirname): Origin {
    const token = io.env.GITHUB_TOKEN
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
                        ...(token && { Authorization: `Bearer ${token}` }),
                    },
                    timeoutMs: REQUEST_TIMEOUT_MS,
                })
            let response = await compare()
            if (await isRateLimited(response)) {
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
