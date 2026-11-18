import { expect, test, type Page } from '@playwright/test'

// MOCK_DEFAULT_TEAM in frontend/src/lib/api.mock.ts
const PROJECT = '/project/997'

const SCENES: { path: string; title: string }[] = [
    { path: 'dashboard', title: 'Dashboards' },
    { path: 'insights', title: 'Product analytics' },
    { path: 'insights/new', title: 'Pageview count • Product analytics' },
    { path: 'replay/home', title: 'Recordings' },
    { path: 'feature_flags', title: 'Feature flags' },
    { path: 'experiments', title: 'Experiments' },
    { path: 'surveys', title: 'Surveys' },
    { path: 'error_tracking', title: 'Error tracking' },
    { path: 'notebooks', title: 'Notebooks' },
    { path: 'settings/project', title: 'Settings - General' },
]

// A layout timing notice that browsers report as an error event on a busy machine.
const BROWSER_NOTICES = /^ResizeObserver loop/

// API requests are left out, because an API request without a fixture gets a 404 on purpose.
function watchForFailures(page: Page): string[] {
    const failures: string[] = []
    const where = (): string => new URL(page.url()).pathname
    const siteFile = (url: string): string | null => {
        const { origin, pathname } = new URL(url)
        return origin === new URL(page.url()).origin && !pathname.startsWith('/api/') ? pathname : null
    }
    page.on('pageerror', (error) => {
        if (!BROWSER_NOTICES.test(error.message)) {
            failures.push(`${where()}: uncaught ${error.message}`)
        }
    })
    page.on('response', (response) => {
        const file = siteFile(response.url())
        if (file && response.status() >= 400) {
            failures.push(`${where()}: ${response.status()} for ${file}`)
        }
    })
    page.on('requestfailed', (request) => {
        const file = siteFile(request.url())
        if (file) {
            failures.push(`${where()}: ${request.failure()?.errorText} for ${file}`)
        }
    })
    return failures
}

async function goToInApp(page: Page, path: string): Promise<void> {
    await page.evaluate((url) => {
        window.history.pushState({}, '', url)
        window.dispatchEvent(new PopStateEvent('popstate'))
    }, path)
}

async function expectNoCrashScreen(page: Page): Promise<void> {
    await expect(page.getByRole('heading', { name: 'An error has occurred' })).toHaveCount(0)
    await expect(page.getByText(/PostHog (crashed while starting|failed to load)/)).toHaveCount(0)
}

test('the mock app boots signed in and renders the core scenes', async ({ page }) => {
    const failures = watchForFailures(page)

    await test.step('boot to the project home', async () => {
        await page.goto('/')
        await expect(page).toHaveURL(`${PROJECT}/home`)
        await expect(page).toHaveTitle('Home • PostHog')
        // WebKit fails a dynamic import that starts while a page load is pending, so routing waits for the load.
        await page.waitForLoadState('load')
        await expectNoCrashScreen(page)
    })

    for (const { path, title } of SCENES) {
        await test.step(path, async () => {
            await goToInApp(page, `${PROJECT}/${path}`)
            await expect(page).toHaveTitle(`${title} • PostHog`)
            await expectNoCrashScreen(page)
        })
    }

    await test.step('debug query loads its web worker', async () => {
        const editorWorker = page.waitForResponse((response) =>
            new URL(response.url()).pathname.startsWith('/static/monacoEditorWorker')
        )
        await goToInApp(page, `${PROJECT}/debug`)
        await expect(page).toHaveTitle('Debug query • PostHog')
        expect((await editorWorker).status()).toBe(200)
    })

    expect(failures).toEqual([])
})
