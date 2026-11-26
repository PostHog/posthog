import { execFile, execFileSync } from 'child_process'
import { copyFile, mkdtemp, rm, writeFile } from 'fs/promises'
import os from 'os'
import path from 'path'
import { promisify } from 'util'

import { FetchResponse, internalFetch } from '~/common/utils/request'

import { Controller, Origin } from './admission'

const REPOSITORY = 'PostHog/posthog'
const MASTER_REF = 'refs/master'
const GIT_TIMEOUT_MS = 120_000
const SHALLOW_MARGIN_S = 24 * 60 * 60
const REQUEST_TIMEOUT_MS = 10_000
const RETRY_WAIT_CAP_MS = 60_000
const RATE_LIMIT_HEADERS = ['x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after']

export type OriginIo = Pick<Controller, 'now' | 'sleep' | 'warn'>

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

async function onMasterInGit(repo: string, remote: string, commit: string): Promise<true> {
    const run = async (cwd: string, env: NodeJS.ProcessEnv, args: string[]): Promise<string> =>
        (await promisify(execFile)('git', args, { cwd, env, timeout: GIT_TIMEOUT_MS })).stdout.trim()
    const inRepo = (...args: string[]): Promise<string> => run(repo, process.env, args)
    const scratchEnv = {
        ...Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith('GIT_'))),
        GIT_CONFIG_NOSYSTEM: '1',
        GIT_CONFIG_GLOBAL: os.devNull,
        GIT_TERMINAL_PROMPT: '0',
        GIT_HTTP_LOW_SPEED_LIMIT: '1000',
        GIT_HTTP_LOW_SPEED_TIME: '30',
    }
    const inScratch = (...args: string[]): Promise<string> => run(scratch, scratchEnv, args)
    const gitDir = path.resolve(repo, await inRepo('rev-parse', '--git-common-dir'))
    const committedS = Number(await inRepo('show', '-s', '--format=%ct', commit))
    const scratch = await mkdtemp(path.join(os.tmpdir(), 'scenario-origin-'))
    try {
        await inScratch('init', '--quiet', '--bare')
        await writeFile(path.join(scratch, 'objects', 'info', 'alternates'), `${path.join(gitDir, 'objects')}\n`)
        await copyFile(path.join(gitDir, 'shallow'), path.join(scratch, 'shallow')).catch((error) => {
            if ((error as { code?: unknown }).code !== 'ENOENT') {
                throw error
            }
        })
        await inScratch(
            'fetch',
            '--quiet',
            '--no-tags',
            '--filter=tree:0',
            `--shallow-since=@${committedS - SHALLOW_MARGIN_S}`,
            remote,
            `+refs/heads/master:${MASTER_REF}`
        )
        await inScratch('merge-base', '--is-ancestor', commit, MASTER_REF)
        return true
    } finally {
        await rm(scratch, { recursive: true, force: true })
    }
}

function firstLineOf(error: unknown): string {
    const { stderr, message } = error as { stderr?: unknown; message?: unknown }
    const text = typeof stderr === 'string' && stderr.trim() ? stderr : String(message)
    return text.trim().split('\n')[0]
}

export function githubOrigin(
    io: OriginIo,
    api = 'https://api.github.com',
    repo = __dirname,
    remote = `https://github.com/${REPOSITORY}`
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
            try {
                return await onMasterInGit(repo, remote, commit)
            } catch (error) {
                io.warn(
                    `Git could not confirm that commit ${commit} is on master (${firstLineOf(error)}). Asking GitHub's API.`
                )
            }
            const compare = (): Promise<FetchResponse> =>
                internalFetch(`${api}/repos/${REPOSITORY}/compare/master...${commit}`, {
                    headers: {
                        Accept: 'application/vnd.github+json',
                        'User-Agent': 'posthog-scenario-runner',
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
