import { randomString } from '../utils'
import { expect, test } from '../utils/workspace-test-base'

test.describe('Invites', () => {
    test('an invited teammate can sign up through the invite link and lands in the organization', async ({
        page,
        browser,
        playwrightSetup,
    }) => {
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })

        // Force link-generation mode so the modal flow is deterministic regardless of
        // whether the environment has an email service configured. Preflight is both
        // server-rendered into POSTHOG_APP_CONTEXT and refreshed via the API, so patch both.
        await page.addInitScript(() => {
            let appContext: any = undefined
            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                get() {
                    if (appContext?.preflight) {
                        appContext.preflight.email_service_available = false
                    }
                    return appContext
                },
                set(value) {
                    appContext = value
                },
                configurable: true,
            })
        })
        await page.route('**/_preflight*', async (route) => {
            const response = await route.fetch()
            const body = await response.json()
            await route.fulfill({ response, json: { ...body, email_service_available: false } })
        })

        await playwrightSetup.login(page, workspace)
        const inviteeEmail = `${randomString('invitee-')}@posthog.com`
        let inviteUrl = ''

        await test.step('generate an invite link from org settings', async () => {
            await page.goto('/settings/organization-members')
            await page.getByTestId('invite-teammate-button').click()
            await page.getByTestId('invite-email-input').fill(inviteeEmail)
            await page.getByTestId('invite-generate-invite-link').click()
            await page.getByRole('button', { name: 'Done' }).click()
        })

        await test.step('read the invite link from the invites table', async () => {
            const link = page.getByTestId('invite-link')
            await expect(link).toBeVisible()
            inviteUrl = (await link.textContent()) ?? ''
            expect(inviteUrl).toMatch(/\/signup\/[0-9a-f-]{36}/)
        })

        await test.step('accept the invite in a fresh browser session', async () => {
            const context = await browser.newContext()
            const invitePage = await context.newPage()
            await invitePage.goto(inviteUrl)
            await invitePage.locator('[data-attr=password]').fill(`E2e!${randomString('pw-')}`)
            await invitePage.locator('[data-attr=first_name]').fill('Invited Hedgehog')
            await invitePage.locator('[data-attr=signup-role-at-organization]').click()
            await invitePage.locator('.Popover__content').getByText('Engineering').click()
            await invitePage.locator('[data-attr=password-signup]').click()
            await invitePage.waitForURL(/\/project\//, { timeout: 30000 })

            const me = await invitePage.request.get('/api/users/@me/')
            expect(me.status()).toBe(200)
            const body = await me.json()
            expect(body.email).toBe(inviteeEmail)
            expect(body.organization.id).toBe(workspace.organization_id)
            await context.close()
        })
    })
})
