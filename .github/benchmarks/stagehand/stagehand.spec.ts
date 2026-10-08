import type { Page, StagehandBrowser } from '@browserbasehq/stagehand'

import { NodeKind } from '../../../frontend/src/queries/schema/schema-general'
import { expect, test as base, type APIRequestContext } from '../../../playwright/node_modules/@playwright/test'
import { PlaywrightSetup, type PlaywrightWorkspaceSetupResult } from '../../../playwright/utils/playwright-setup'
import { LOGIN_PASSWORD, LOGIN_USERNAME } from '../../../playwright/utils/playwright-test-core'
import { launchStagehand } from './bootstrap'

const test = base.extend<{ sh: { browser: StagehandBrowser; page: Page }; setup: PlaywrightSetup }>({
    sh: async ({ playwright, viewport }, use, testInfo) => {
        const session = await launchStagehand(
            playwright.chromium,
            viewport ?? { width: 1280, height: 720 },
            9222 + testInfo.workerIndex
        )
        try {
            await use(session)
        } finally {
            if (testInfo.status !== testInfo.expectedStatus) {
                try {
                    for (const page of await session.browser.context.pages()) {
                        await testInfo.attach(`stagehand-${page.pageId}`, {
                            body: Buffer.from(await page.screenshot()),
                            contentType: 'image/png',
                        })
                        await testInfo.attach(`stagehand-${page.pageId}-state`, {
                            body: JSON.stringify({
                                url: await page.url(),
                                viewport: await page.evaluate(() => [innerWidth, innerHeight]),
                            }),
                            contentType: 'application/json',
                        })
                    }
                } catch {}
            }
            await session.close()
        }
    },
    setup: async ({ baseURL }, use) => {
        const setup = new PlaywrightSetup(baseURL)
        try {
            await use(setup)
        } finally {
            await setup.dispose()
        }
    },
})

async function visible(page: Page, selector: string, timeout = 40000): Promise<void> {
    expect(await page.waitForSelector(selector, { state: 'visible', timeout })).toBe(true)
}

async function fill(page: Page, selector: string, value: string): Promise<void> {
    await visible(page, selector)
    await expect.poll(() => page.locator(selector).count()).toBe(1)
    await page.locator(selector).fill(value)
}

async function click(page: Page, selector: string): Promise<void> {
    await visible(page, selector)
    await expect.poll(() => page.locator(selector).count()).toBe(1)
    await page.locator(selector).click()
}

async function urlIs(page: Page, expected: string | RegExp): Promise<void> {
    const resolved = typeof expected === 'string' ? new URL(expected, 'http://localhost:8000').href : expected
    const readUrl = async (): Promise<string> => {
        try {
            return await page.url()
        } catch (error) {
            if (error instanceof Error && error.message.includes('Execution context was destroyed')) return ''
            throw error
        }
    }
    if (typeof resolved === 'string') await expect.poll(readUrl).toBe(resolved)
    else await expect.poll(readUrl).toMatch(resolved)
}

async function gotoLoginRedirect(page: Page, destination: string): Promise<void> {
    try {
        await page.goto(destination, { waitUntil: 'domcontentloaded' })
    } catch (error) {
        // A redirect can replace the execution context after navigation has already reached the login page.
        if (!(error instanceof Error) || !error.message.includes('Execution context was destroyed')) throw error
    }
    await urlIs(page, /\/login/)
}

async function textContains(page: Page, selector: string, text: string): Promise<void> {
    await visible(page, selector)
    await expect.poll(() => page.locator(selector).innerText()).toContain(text)
}

async function credentials(page: Page, email: string, password: string): Promise<void> {
    await fill(page, '[data-attr=login-email]', email)
    await expect.poll(() => page.locator('[data-attr=login-email]').inputValue()).toBe(email)
    await page.evaluate(() => (document.querySelector('[data-attr=login-email]') as HTMLInputElement).blur())
    await visible(page, '[data-attr=password]', 5000)
    await fill(page, '[data-attr=password]', password)
    await expect.poll(() => page.locator('[data-attr=password]').inputValue()).toBe(password)
}

async function login(
    browser: StagehandBrowser,
    request: APIRequestContext,
    workspace: PlaywrightWorkspaceSetupResult
): Promise<void> {
    const response = await request.post('/api/login/', {
        data: { email: workspace.user_email, password: LOGIN_PASSWORD },
    })
    expect(response.ok()).toBe(true)
    await browser.context.addCookies((await request.storageState()).cookies)
}

test.describe('Auth', () => {
    let workspace: PlaywrightWorkspaceSetupResult
    const redirectInsightName = 'Authentication redirect insight'

    test.beforeAll(async ({ setup }) => {
        workspace = await setup.createWorkspace({
            skip_onboarding: true,
            no_demo_data: true,
            insights: [
                {
                    name: redirectInsightName,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                        },
                    },
                },
            ],
        })
    })

    test.beforeEach(async ({ sh, request, baseURL }) => {
        await login(sh.browser, request, workspace)
        await sh.page.goto(`${baseURL}/project/${workspace.team_id}`, { waitUntil: 'load' })
        await click(sh.page, '[data-attr=new-account-menu-button]')
    })

    test('Logout', async ({ sh: { page } }) => {
        await click(page, '[data-attr=new-account-menu-logout-button]')
        await urlIs(page, '/login')
    })

    test('Logout and login', async ({ sh: { page } }) => {
        await click(page, '[data-attr=new-account-menu-logout-button]')
        await credentials(page, LOGIN_USERNAME, LOGIN_PASSWORD)
        await click(page, '[type=submit]')
        await urlIs(page, /\/project\/\d+/)
    })

    test('Logout and verify Google login button has correct link', async ({ sh: { page } }) => {
        await page.addInitScript(() => {
            let context: { preflight?: { available_social_auth_providers?: Record<string, boolean> } } | undefined
            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                get() {
                    if (context?.preflight) {
                        context.preflight.available_social_auth_providers ??= {}
                        context.preflight.available_social_auth_providers['google-oauth2'] = true
                    }
                    return context
                },
                set(value: typeof context) {
                    context = value
                },
                configurable: true,
            })
        })
        await click(page, '[data-attr=new-account-menu-logout-button]')
        await visible(page, 'a[href="/login/google-oauth2/"]')
    })

    test('Try logging in improperly and then properly', async ({ sh: { page } }) => {
        await click(page, '[data-attr=new-account-menu-logout-button]')
        await credentials(page, LOGIN_USERNAME, 'wrong password')
        await click(page, '[type=submit]')
        await expect
            .poll(() =>
                page.evaluate(() => {
                    const elements = [...document.querySelectorAll('p, div, span')]
                    return elements.some(
                        (element) =>
                            element.textContent === 'Invalid email or password.' &&
                            (element as HTMLElement).checkVisibility()
                    )
                })
            )
            .toBe(true)
        await fill(page, '[data-attr=password]', LOGIN_PASSWORD)
        await click(page, '[type=submit]')
        await urlIs(page, /\/project\/\d+/)
    })

    test('Redirect to appropriate place after login', async ({ sh: { browser, page }, baseURL }) => {
        await browser.context.clearCookies()
        await page.goto(`${baseURL}/activity/events`, { waitUntil: 'domcontentloaded' })
        await urlIs(page, /\/login/)
        await credentials(page, LOGIN_USERNAME, LOGIN_PASSWORD)
        await click(page, '[type=submit]')
        await urlIs(page, /\/activity\/events/)
    })

    test('Redirect to appropriate place after login with complex URL', async ({ sh: { browser, page }, baseURL }) => {
        await browser.context.clearCookies()
        await test.step('Follow the login redirect with the search parameter', () =>
            gotoLoginRedirect(page, `${baseURL}/insights?search=testString`))
        await credentials(page, LOGIN_USERNAME, LOGIN_PASSWORD)
        await click(page, '[type=submit]')
        await urlIs(page, /search%3DtestString/)
        await textContains(page, '.saved-insight-empty-state', 'testString')
    })

    test('Redirect to a saved insight after login', async ({ sh: { browser, page }, baseURL }) => {
        const insightUrl = `/project/${workspace.team_id}/insights/${workspace.created_insights![0].short_id}`
        await browser.context.clearCookies()
        await page.goto(`${baseURL}${insightUrl}`, { waitUntil: 'domcontentloaded' })
        await urlIs(page, /\/login/)
        await credentials(page, workspace.user_email, LOGIN_PASSWORD)
        await click(page, '[type=submit]')
        await urlIs(page, insightUrl)
        await textContains(page, '[data-attr=scene-name]', redirectInsightName)
    })

    test('Cannot access signup page if authenticated', async ({ sh: { page }, baseURL }) => {
        await page.goto(`${baseURL}/signup`, { waitUntil: 'load' })
        await urlIs(page, /\/project\/\d+/)
    })

    test('Logout in another tab results in logout in the current tab too', async ({
        sh: { browser, page },
        baseURL,
        viewport,
    }) => {
        const secondPage = await browser.context.newPage()
        const size = viewport ?? { width: 1280, height: 720 }
        await secondPage.setViewportSize(size.width, size.height)
        await secondPage.goto(`${baseURL}/`, { waitUntil: 'load' })
        await visible(secondPage, '[data-attr=new-account-menu-button]', 30000)
        await click(secondPage, '[data-attr=new-account-menu-button]')
        await click(secondPage, '[data-attr=new-account-menu-logout-button]')
        await urlIs(secondPage, /\/login/)
        await page.reload({ waitUntil: 'load' })
        await urlIs(page, /\/login/)
    })
})

test.describe('Before Onboarding', () => {
    let workspace: PlaywrightWorkspaceSetupResult
    test.beforeAll(async ({ setup }) => {
        workspace = await setup.createWorkspace({ no_demo_data: true })
    })
    test('Navigate to a settings page even when a product has not been set up', async ({ sh, request, baseURL }) => {
        await login(sh.browser, request, workspace)
        await sh.page.goto(`${baseURL}/settings/user`, { waitUntil: 'load' })
        await textContains(sh.page, 'h1', 'Settings - Profile')
        await sh.page.goto(`${baseURL}/settings/organization`, { waitUntil: 'load' })
        await textContains(sh.page, 'h1', 'Settings - General')
    })
})
