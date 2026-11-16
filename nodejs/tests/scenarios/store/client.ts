import { existsSync, readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { promisify } from 'util'
import { gzip } from 'zlib'

import { internalFetch } from '~/common/utils/request'

import { INGEST_PATH } from './server'

export const STORE_URL = 'SCENARIO_STORE_URL'

const REQUEST_TIMEOUT_MS = 30_000

const gzipAsync = promisify(gzip)

export type StoreReport = { scorecard: Record<string, unknown>; host?: string }

export type StoreOutcome = { stored: boolean; problem?: string }

type StoreTarget = { url: string; token: string }

export const storeTokenPathOf = (env: NodeJS.ProcessEnv): string =>
    path.join(env.HOME || os.homedir(), '.config', 'posthog', 'scenario-runs', 'store-token')

function targetOf(env: NodeJS.ProcessEnv): { target?: StoreTarget; problem?: string } {
    const url = env[STORE_URL]
    if (!url) {
        return {}
    }
    const tokenPath = storeTokenPathOf(env)
    const token = existsSync(tokenPath) ? readFileSync(tokenPath, 'utf8').trim() : ''
    if (token === '') {
        return { problem: `${STORE_URL} is set, but ${tokenPath} holds no run token` }
    }
    return { target: { url: url.replace(/\/+$/, ''), token } }
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
    })
    if (response.status === 200 || response.status === 201) {
        return { stored: true }
    }
    return { stored: false, problem: `the run store answered ${response.status}: ${await response.text()}` }
}

export async function reportToStore(report: StoreReport, env: NodeJS.ProcessEnv): Promise<StoreOutcome> {
    const { target, problem } = targetOf(env)
    if (target === undefined) {
        return { stored: false, problem }
    }
    return await post(report, target).catch((error: Error) => ({
        stored: false,
        problem: `the run store did not answer: ${error.message}`,
    }))
}
