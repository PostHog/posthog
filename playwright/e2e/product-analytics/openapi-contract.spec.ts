import { expect } from '@playwright/test'

import { test } from '../../utils/playwright-test-base'

test('validates product analytics project API contract', async ({ page }) => {
    const projectResponse = await page.request.get('/api/projects/@current/')

    expect(projectResponse.ok()).toBe(true)

    const project = await projectResponse.json()
    expect(typeof project.id).toBe('number')
    expect(typeof project.name).toBe('string')
})
