import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'

import { defaultConfig } from '~/common/config/config'
import { internalFetch } from '~/common/utils/request'

import { scratchSchema } from '../environment/stack'
import { STORE_URL, storeTokenPathOf } from './client'
import { RUNS_PATH } from './routes'
import type { Run } from './runs'
import { startStore } from './server'

const TOKEN = 'test-run-token'

export const UNREACHABLE_STORE = 'http://127.0.0.1:1'

export function storeEnvOf(home: string, url: string): NodeJS.ProcessEnv {
    const env = { HOME: home, [STORE_URL]: url }
    const tokenPath = storeTokenPathOf(env)
    mkdirSync(path.dirname(tokenPath), { recursive: true })
    writeFileSync(tokenPath, `${TOKEN}\n`, { mode: 0o600 })
    return env
}

export type TestStore = {
    envOf: (home: string) => NodeJS.ProcessEnv
    read: (runId: string) => Promise<Run | undefined>
    close: () => Promise<void>
}

export async function startTestStore(name: string): Promise<TestStore> {
    const schema = scratchSchema(defaultConfig.DATABASE_URL, `scenario_store_${name}_${process.pid}`, [])
    await schema.create()
    const store = await startStore({ databaseUrl: schema.url, token: TOKEN, port: 0 })
    return {
        envOf: (home) => storeEnvOf(home, store.url),
        read: async (runId) => {
            const response = await internalFetch(`${store.url}${RUNS_PATH}/${runId}`)
            return response.status === 200 ? ((await response.json()) as Run) : undefined
        },
        close: async () => {
            await store.close()
            await schema.drop()
        },
    }
}
