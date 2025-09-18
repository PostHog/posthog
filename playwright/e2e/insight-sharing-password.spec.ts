/**
 * Test password-protected sharing functionality
 */
import { expect } from '@playwright/test'

import { InsightVizNode, NodeKind, TrendsQuery } from '../../frontend/src/queries/schema/schema-general'
import { test } from '../utils/workspace-test-base'

type InsightCreationPayload = {
    name: string
    query: InsightVizNode<TrendsQuery>
}

type SharingConfigurationResponse = {
    access_token: string
    created_at: string
    enabled: boolean
    password_required: boolean
    settings: any
    share_passwords: any[]
}

type SharePasswordResponse = {
    id: string
    password: string
    note: string
    created_at: string
    created_by_email: string
}

test('password-protected insight sharing', async ({ page, playwrightSetup }) => {
    // Set fixed time for consistent snapshots (November 3, 2024 at noon UTC)
    await page.clock.setFixedTime(new Date('2024-11-03T12:00:00Z'))

    // Create workspace with API key
    const workspace = await playwrightSetup.createWorkspace('Password Sharing Test Org')

    // Create a trends insight via API
    const payload: InsightCreationPayload = {
        name: 'Password Protected Insight',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                    },
                ],
                dateRange: {
                    date_from: '2024-10-04',
                    date_to: '2024-11-03',
                    explicitDate: true,
                },
            },
        },
    }

    const insightResponse = await page.request.post(`/api/projects/${workspace.team_id}/insights/`, {
        headers: {
            Authorization: `Bearer ${workspace.personal_api_key}`,
            'Content-Type': 'application/json',
        },
        data: payload,
    })

    expect(insightResponse.ok()).toBe(true)
    const insightData = await insightResponse.json()
    expect(insightData.short_id).toBeTruthy()

    // Enable sharing with password protection
    const sharingResponse = await page.request.patch(
        `/api/projects/${workspace.team_id}/insights/${insightData.id}/sharing`,
        {
            headers: {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            },
            data: {
                enabled: true,
                password_required: true,
            },
        }
    )

    expect(sharingResponse.ok()).toBe(true)
    const sharingData: SharingConfigurationResponse = await sharingResponse.json()
    expect(sharingData.enabled).toBe(true)
    expect(sharingData.password_required).toBe(true)
    expect(sharingData.access_token).toBeTruthy()

    // Create a password for the shared insight
    const passwordResponse = await page.request.post(
        `/api/projects/${workspace.team_id}/insights/${insightData.id}/sharing/passwords/`,
        {
            headers: {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            },
            data: {
                raw_password: 'testpassword',
                note: 'Test password for Playwright test',
            },
        }
    )

    expect(passwordResponse.ok()).toBe(true)
    const passwordData: SharePasswordResponse = await passwordResponse.json()
    expect(passwordData.password).toBe('testpassword')
    expect(passwordData.note).toBe('Test password for Playwright test')

    // Navigate to the shared insight URL (without being logged in)
    const sharedUrl = `/shared/${sharingData.access_token}`
    await page.goto(sharedUrl)

    // Verify the password login page appears
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('text=Unlock')).toBeVisible()
    await expect(page.locator('text=Access share')).toBeVisible()

    // Take a snapshot of the password login page
    await page.screenshot({
        path: '__snapshots__/insight-sharing-password-login.png',
        fullPage: true,
    })

    // First try wrong password
    await page.fill('input[type="password"]', 'wrongpassword')
    await page.click('text=Unlock')

    // Verify error message appears
    await expect(page.locator('text=Incorrect password')).toBeVisible()

    // Verify we're still on the password page (not authenticated)
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('text=Unlock')).toBeVisible()
    await expect(page.locator('text=Access share')).toBeVisible()

    // Now enter the correct password
    await page.fill('input[type="password"]', 'testpassword')
    await page.click('text=Unlock')

    // Wait for the insight to load after successful authentication
    await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible()

    // Verify we're viewing the correct insight by checking the title
    await expect(page.locator('text=Password Protected Insight')).toBeVisible()

    // Verify the insight content is loaded (either chart with canvas or empty state message)
    await expect(
        page
            .locator('[data-attr="insights-graph"] canvas')
            .or(page.locator('text=There are no matching events for this query'))
    ).toBeVisible()

    // Verify the URL still shows the shared access token (not redirected to regular insight page)
    await expect(page).toHaveURL(new RegExp(`/shared/${sharingData.access_token}`))
})
