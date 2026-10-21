import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

// The toolbar launches on a customer's site, so the test serves a stand-in for one: a bare page with
// the posthog-js snippet. Playwright serves it on the app origin, so the page loads posthog-js and the
// toolbar bundle from the app's /static/. posthog-js opens the toolbar only when the token in the launch
// link matches the token the page initializes with, so the page must use the project's real token.
const TOOLBAR_HOST_PATH = '/toolbar-e2e-host'

function toolbarHostPage(apiToken: string): string {
    return `<!doctype html>
<html>
    <head>
        <script src="/static/array.js"></script>
    </head>
    <body>
        <script>
            posthog.init(${JSON.stringify(apiToken)}, { api_host: window.location.origin })
        </script>
    </body>
</html>`
}

test.describe('Toolbar', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Toolbar loads', async ({ page, request }) => {
        const team = await request.get(`/api/environments/${workspace!.team_id}/`, {
            headers: { Authorization: `Bearer ${workspace!.personal_api_key}` },
        })
        expect(team.ok()).toBe(true)
        const apiToken: string = (await team.json()).api_token
        await page.route(
            (url) => url.pathname === TOOLBAR_HOST_PATH,
            (route) => route.fulfill({ contentType: 'text/html', body: toolbarHostPage(apiToken) })
        )

        await page.goToMenuItem('toolbar')
        await page.getByText('Add authorized URL').click()

        const loc = await page.evaluate(() => window.location)
        await page.locator('[data-attr="url-input"]').fill(`http://${loc.host}${TOOLBAR_HOST_PATH}`)
        await page.locator('[data-attr="url-save"]').click()

        const href = await page.locator('[data-attr="toolbar-open"]').first().getAttribute('href')
        if (href) {
            await page.goto(href)
        }

        await expect(page.locator('#__POSTHOG_TOOLBAR__ .Toolbar')).toBeVisible({ timeout: 5000 })
    })

    test('Toolbar item in sidebar has launch options', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.getByText('Add authorized URL').click()
        await expect(page).toHaveURL(/.*\/toolbar/)
    })

    test('Can open add authorized URL form', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.locator('[data-attr="toolbar-add-url"]').click()
        await expect(page.locator('[data-attr="url-input"]')).toBeVisible()
    })
})
