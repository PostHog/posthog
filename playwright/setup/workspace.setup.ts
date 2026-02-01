import { type FullConfig, request as playwrightRequest } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

import { LOGIN_PASSWORD } from '../utils/playwright-test-core'

export const STORAGE_STATE_PATH = path.join(__dirname, '..', '.auth', 'storage-state.json')
export const WORKSPACE_DATA_PATH = path.join(__dirname, '..', '.auth', 'workspace.json')

async function globalSetup(config: FullConfig): Promise<void> {
    const baseURL = config.projects[0].use.baseURL || 'http://localhost:8000'

    const request = await playwrightRequest.newContext({ baseURL })

    const createResponse = await request.post(`${baseURL}/api/setup_test/organization_with_team/`, {
        data: { use_current_time: true },
    })
    const result = await createResponse.json()

    if (!result.success) {
        throw new Error(`Failed to create workspace: ${result.error}`)
    }

    const workspace = result.result

    // Login via API to establish session cookies
    await request.post(`${baseURL}/api/login/`, {
        data: {
            email: workspace.user_email,
            password: LOGIN_PASSWORD,
        },
    })

    // Save auth state for reuse by test projects
    fs.mkdirSync(path.dirname(STORAGE_STATE_PATH), { recursive: true })
    await request.storageState({ path: STORAGE_STATE_PATH })

    // Save workspace data for test files to read
    fs.writeFileSync(WORKSPACE_DATA_PATH, JSON.stringify(workspace, null, 2))

    await request.dispose()
}

export default globalSetup
