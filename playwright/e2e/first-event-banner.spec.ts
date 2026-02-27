import { Page } from '@playwright/test'

import { expect, test } from '../utils/workspace-test-base'

function extractEventNamesFromPostHogCapture(postData: string | null): string[] {
    if (!postData) {
        return []
    }

    // Most commonly, posthog-js sends a JSON payload with `batch`
    try {
        const json = JSON.parse(postData) as any
        if (Array.isArray(json?.batch)) {
            return json.batch.map((e: any) => e?.event).filter(Boolean)
        }
        if (typeof json?.event === 'string') {
            return [json.event]
        }
    } catch {
        // ignore
    }

    // Fallback: posthog-js can send urlencoded `data=<base64(json)>`
    try {
        const params = new URLSearchParams(postData)
        const data = params.get('data')
        if (data) {
            const decoded = Buffer.from(data, 'base64').toString('utf8')
            const json = JSON.parse(decoded) as any
            if (Array.isArray(json?.batch)) {
                return json.batch.map((e: any) => e?.event).filter(Boolean)
            }
            if (typeof json?.event === 'string') {
                return [json.event]
            }
        }
    } catch {
        // ignore
    }

    return []
}

async function patchAppContext(page: Page, { hasIngestedEvent }: { hasIngestedEvent: boolean }): Promise<void> {
    await page.addInitScript(
        ({ hasIngestedEvent }) => {
            const persistedFlag = 'growth.first_event_banner'
            let _ctx: any

            const patch = (ctx: any): any => {
                if (!ctx) {
                    return ctx
                }

                ctx.persisted_feature_flags = Array.from(
                    new Set([...(ctx.persisted_feature_flags || []), persistedFlag])
                )

                if (ctx.current_team) {
                    ctx.current_team = { ...ctx.current_team, ingested_event: hasIngestedEvent }
                }

                return ctx
            }

            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                configurable: true,
                get() {
                    return _ctx
                },
                set(value) {
                    _ctx = patch(value)
                },
            })
        },
        { hasIngestedEvent }
    )
}

test.describe('First event banner', () => {
    test('shows banner for new users and tracks impression + CTA click', async ({ page, playwrightSetup }) => {
        const capturedEventNames: string[] = []

        await page.route('**/e/**', async (route) => {
            if (route.request().method() !== 'POST') {
                await route.continue()
                return
            }

            capturedEventNames.push(...extractEventNamesFromPostHogCapture(route.request().postData()))
            await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
        })

        const workspace = await playwrightSetup.createWorkspace({ no_demo_data: true })

        await patchAppContext(page, { hasIngestedEvent: false })
        await playwrightSetup.loginAndNavigateToTeam(page, workspace)
        await page.goto(`/project/${workspace.team_id}/home`)

        await expect(page.locator('[data-attr=first-event-banner]')).toBeVisible()

        await expect.poll(() => capturedEventNames.includes('banner.impression')).toBeTruthy()

        await page.locator('[data-attr=first-event-banner-create-event]').click()

        await expect.poll(() => capturedEventNames.includes('banner.cta_click')).toBeTruthy()

        await expect(page.locator('[data-attr=event-definition-name-input]')).toBeVisible()
    })

    test('does not show banner once events have been ingested', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ no_demo_data: true })

        await patchAppContext(page, { hasIngestedEvent: true })
        await playwrightSetup.loginAndNavigateToTeam(page, workspace)
        await page.goto(`/project/${workspace.team_id}/home`)

        await expect(page.locator('[data-attr=first-event-banner]')).not.toBeVisible()
    })
})
