import { existsSync, readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { promisify } from 'util'
import { gzip } from 'zlib'

import { internalFetch } from '~/common/utils/request'

import { INGEST_PATH } from './routes'

export const STORE_URL = 'SCENARIO_STORE_URL'

const REQUEST_TIMEOUT_MS = 30_000
const PROBLEM_BODY_CHARS = 200
const MAX_RESPONSE_BYTES = 64 * 1024

const gzipAsync = promisify(gzip)

export type StoreReport = { scorecard: Record<string, unknown>; host?: string }

export type StoreOutcome = { stored: boolean; problem?: string }

type StoreTarget = { url: string; token: string }

export const storeTokenPathOf = (env: NodeJS.ProcessEnv): string =>
    path.join(env.HOME || os.homedir(), '.config', 'posthog', 'scenario-runs', 'store-token')

function targetOf(env: NodeJS.ProcessEnv): { target: StoreTarget } | { problem?: string } {
    const url = env[STORE_URL]
    if (!url) {
        return {}
    }
    const tokenPath = storeTokenPathOf(env)
    try {
        const token = existsSync(tokenPath) ? readFileSync(tokenPath, 'utf8').trim() : ''
        return token === ''
            ? { problem: `${STORE_URL} is set, but ${tokenPath} holds no run token` }
            : { target: { url: url.replace(/\/+$/, ''), token } }
    } catch (error) {
        return { problem: `the run token could not be read: ${(error as Error).message}` }
    }
}

async function post(report: StoreReport, { url, token }: StoreTarget): Promise<StoreOutcome> {
    const response = await internalFetch(`${url}${INGEST_PATH}`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
            'Content-Encoding': 'gzip',
        },
        body: await gzipAsync(JSON.stringify(report)),
        timeoutMs: REQUEST_TIMEOUT_MS,
        maxResponseBytes: MAX_RESPONSE_BYTES,
    })
    if (response.status === 200 || response.status === 201) {
        await response.dump()
        return { stored: true }
    }
    const body = (await response.text().catch((error: Error) => error.message)).slice(0, PROBLEM_BODY_CHARS)
    return { stored: false, problem: `the run store answered ${response.status}: ${body}` }
}

export async function reportToStore(report: StoreReport, env: NodeJS.ProcessEnv): Promise<StoreOutcome> {
    const found = targetOf(env)
    if (!('target' in found)) {
        return { stored: false, problem: found.problem }
    }
    return await post(report, found.target).catch((error: Error) => ({
        stored: false,
        problem: `the run store did not answer: ${error.message}`,
    }))
}
