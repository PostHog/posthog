import { mockFeatureFlags } from '@playwright-utils/mockApi'
import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Locator, Page } from '@playwright/test'

import { FEATURE_FLAGS } from 'lib/constants'

import { billingJson } from '~/mocks/fixtures/_billing'

/**
 * The usage and spend pages, with billing's answers mocked in the browser.
 *
 * CI has no billing behind the dev stack, so every /api/billing route the pages read is fulfilled
 * here. What this covers is the pages' side of the contract with billing: the one request a page
 * makes and the filters it carries, the project filter while its list loads, which export the menu
 * names, the sentence shown when billing refuses a read, and the date presets on offer.
 *
 * Run against a local PostHog:
 *
 *   BASE_URL=http://localhost:8010 \
 *     pnpm --filter=@posthog/playwright exec playwright test products/billing/frontend/e2e/billing-usage-spend.spec.ts
 */

interface Series {
    id: number
    label: string
    data: number[]
    dates: string[]
    breakdown_type: 'type' | 'team' | 'multiple' | null
    breakdown_value: string | string[] | null
}

interface Answer {
    status?: number
    json: unknown
}

type Answering = (params: URLSearchParams) => Answer

interface BillingReads {
    usage: URLSearchParams[]
    spend: URLSearchParams[]
}

type Kind = 'usage' | 'spend'

const EVENTS = 'event_count_in_period'
const RECORDINGS = 'recording_count_in_period'
const DELETED_TEAM_ID = 424242
const DATE = /^\d{4}-\d{2}-\d{2}$/

/** A week of days ending yesterday, which is the last day billing reports on. */
const DATES = Array.from({ length: 7 }, (_, index) => {
    const day = new Date()
    day.setUTCDate(day.getUTCDate() - 7 + index)
    return day.toISOString().slice(0, 10)
})

const CREDIT_OVERVIEW = {
    eligible: false,
    estimated_monthly_credit_amount_usd: null,
    status: 'none',
    invoice_url: null,
    collection_method: null,
    cc_last_four: null,
    email: null,
    credit_brackets: [],
}

function timeseries(results: Series[]): Answer {
    return { json: { status: 'ok', type: 'timeseries', customer_id: billingJson.customer_id, results } }
}

function byProduct(): Series[] {
    return [
        {
            id: 1,
            label: 'Events',
            data: [10, 20, 30, 40, 50, 60, 70],
            dates: DATES,
            breakdown_type: 'type',
            breakdown_value: EVENTS,
        },
        {
            id: 2,
            label: 'Recordings',
            data: [1, 2, 3, 4, 5, 6, 7],
            dates: DATES,
            breakdown_type: 'type',
            breakdown_value: RECORDINGS,
        },
    ]
}

function byProject(teamId: string, teamName: string): Series[] {
    return [
        {
            id: 1,
            label: `Events - ${teamName}`,
            data: [8, 16, 24, 32, 40, 48, 56],
            dates: DATES,
            breakdown_type: 'multiple',
            breakdown_value: [EVENTS, teamId],
        },
        {
            id: 2,
            label: 'All other projects',
            data: [2, 4, 6, 8, 10, 12, 14],
            dates: DATES,
            breakdown_type: 'multiple',
            breakdown_value: [EVENTS, 'other'],
        },
    ]
}

function refusal(code: string, detail: string): Answer {
    return { status: 400, json: { type: 'validation_error', code, detail, attr: null } }
}

/** Answers with a product breakdown, or a project breakdown when the page asks for one. */
function answerByBreakdown(workspace: PlaywrightWorkspaceSetupResult): Answering {
    return (params) =>
        timeseries(
            params.get('breakdowns')?.includes('team') ? byProject(workspace.team_id, workspace.team_name) : byProduct()
        )
}

async function mockBilling(
    page: Page,
    workspace: PlaywrightWorkspaceSetupResult,
    answers: { usage?: Answering; spend?: Answering; teamOptionsDelayMs?: number } = {}
): Promise<BillingReads> {
    const reads: BillingReads = { usage: [], spend: [] }
    const answering: Record<Kind, Answering> = {
        usage: answers.usage ?? answerByBreakdown(workspace),
        spend: answers.spend ?? answerByBreakdown(workspace),
    }

    await page.route(/\/api\/billing\/?(\?.*)?$/, (route) => route.fulfill({ json: billingJson }))
    await page.route(/\/api\/billing\/credits\/overview/, (route) => route.fulfill({ json: CREDIT_OVERVIEW }))
    await page.route(/\/api\/billing\/usage\/team_options\//, async (route) => {
        if (answers.teamOptionsDelayMs) {
            await new Promise((resolve) => setTimeout(resolve, answers.teamOptionsDelayMs))
        }
        await route.fulfill({ json: { team_id_options: [Number(workspace.team_id), DELETED_TEAM_ID] } })
    })
    for (const kind of ['usage', 'spend'] as Kind[]) {
        await page.route(new RegExp(`/api/billing/${kind}/(\\?.*)?$`), (route) => {
            const params = new URL(route.request().url()).searchParams
            reads[kind].push(params)
            const answer = answering[kind](params)
            return route.fulfill({ status: answer.status ?? 200, json: answer.json })
        })
    }
    await page.route(/\/api\/billing\/(usage|spend)\/export\//, (route) =>
        route.fulfill({
            status: 200,
            headers: {
                'content-type': 'text/csv',
                'content-disposition': 'attachment; filename="billing.csv"',
            },
            body: 'date,product,usage\n',
        })
    )
    return reads
}

async function openProjects(page: Page, kind: Kind): Promise<Locator> {
    await page.getByTestId(`billing-${kind}-projects`).click()
    const options = page.locator('.Popover').last()
    await expect(options.getByText(`ID: ${DELETED_TEAM_ID} (deleted)`)).toBeVisible()
    return options
}

async function openExportMenu(page: Page): Promise<void> {
    await page.getByRole('button', { name: 'Export CSV' }).click()
    await expect(page.getByRole('menuitem').first()).toBeVisible()
}

async function openPage(page: Page, kind: Kind): Promise<void> {
    await page.goto(`/organization/billing/${kind}`)
    // A cold dev server can take a while to serve the app shell, and the page's own asserts
    // should not spend their timeout on it.
    await expect(page.getByText('Break down by')).toBeVisible({ timeout: 30000 })
}

test.describe('Billing usage and spend', () => {
    test.setTimeout(90000)
    let workspace: PlaywrightWorkspaceSetupResult

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await mockFeatureFlags(page, { [FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]: true })
        await playwrightSetup.login(page, workspace)
    })

    test.describe('usage', () => {
        test('reads the period in one request and lists a series per product', async ({ page }) => {
            const reads = await mockBilling(page, workspace)
            await openPage(page, 'usage')

            const table = page.getByRole('table')
            await expect(table.getByText('Events', { exact: true })).toBeVisible()
            await expect(table.getByText('Recordings', { exact: true })).toBeVisible()

            expect(reads.usage).toHaveLength(1)
            const [params] = reads.usage
            expect(params.get('breakdowns')).toBe('["type"]')
            expect(params.get('start_date')).toMatch(DATE)
            expect(params.get('end_date')).toMatch(DATE)
            expect(params.get('team_ids')).toBeNull()
            expect(params.get('top_projects')).toBeNull()
        })

        test('holds the project filter while its list loads, then offers every project billing has seen', async ({
            page,
        }) => {
            await mockBilling(page, workspace, { teamOptionsDelayMs: 1500 })
            await openPage(page, 'usage')

            await expect(page.getByPlaceholder('Loading projects…')).toBeDisabled()
            await expect(page.getByTestId('billing-usage-projects')).toBeVisible({ timeout: 10000 })

            const options = await openProjects(page, 'usage')
            await expect(options.getByText(workspace.team_name, { exact: true })).toBeVisible()
        })

        test('a project selection narrows the request and names the export, until it covers every project', async ({
            page,
        }) => {
            const reads = await mockBilling(page, workspace)
            await openPage(page, 'usage')
            await expect(page.getByRole('table')).toBeVisible()

            let options = await openProjects(page, 'usage')
            await options.getByText(workspace.team_name, { exact: true }).click()
            await expect(page.getByText('1/2 selected')).toBeVisible()
            await page.keyboard.press('Escape')

            await expect.poll(() => reads.usage.at(-1)?.get('team_ids')).toBe(`[${workspace.team_id}]`)
            await openExportMenu(page)
            await expect(page.getByRole('menuitem', { name: 'Selected projects in this period (1)' })).toBeVisible()
            await page.keyboard.press('Escape')

            options = await openProjects(page, 'usage')
            await options.getByRole('button', { name: 'Select all' }).click()
            await expect(page.getByText('All 2 selected')).toBeVisible()
            await page.keyboard.press('Escape')

            // Every project is the whole organization, which is a read with no filter at all.
            await expect.poll(() => reads.usage.length).toBeGreaterThan(2)
            expect(reads.usage.at(-1)?.get('team_ids')).toBeNull()
            await openExportMenu(page)
            await expect(page.getByRole('menuitem', { name: 'All projects in this period' })).toBeVisible()
        })

        test('a project breakdown asks for the top projects and shows the rest folded', async ({ page }) => {
            const reads = await mockBilling(page, workspace)
            await openPage(page, 'usage')
            await expect(page.getByRole('table')).toBeVisible()

            await page.getByText('Break down by').locator('..').getByText('Project', { exact: true }).click()

            await expect.poll(() => reads.usage.at(-1)?.get('breakdowns')).toBe('["type","team"]')
            expect(reads.usage.at(-1)?.get('top_projects')).toBe('20')
            await expect(page.getByText('Show projects')).toBeVisible()
            await expect(page.getByText('Top 20', { exact: true })).toBeVisible()

            const table = page.getByRole('table')
            await expect(table.getByText(`Events - ${workspace.team_name}`)).toBeVisible()
            await expect(table.getByText('All other projects')).toBeVisible()

            await openExportMenu(page)
            await expect(
                page.getByRole('menuitem', { name: "The chart's series (top 20 and the rest folded)" })
            ).toBeVisible()
        })

        test('the export carries the page filters', async ({ page }) => {
            await mockBilling(page, workspace)
            await openPage(page, 'usage')
            await expect(page.getByRole('table')).toBeVisible()

            await openExportMenu(page)
            const [download] = await Promise.all([
                page.waitForEvent('download'),
                page.getByRole('menuitem', { name: 'All projects in this period' }).click(),
            ])

            const params = new URL(download.url()).searchParams
            expect(download.url()).toContain('/api/billing/usage/export/')
            expect(params.get('breakdowns')).toBe('["type"]')
            expect(params.get('start_date')).toMatch(DATE)
            expect(params.get('end_date')).toMatch(DATE)
            expect(params.get('team_ids')).toBeNull()
        })

        test('offers day-or-coarser presets that fit in one request', async ({ page }) => {
            await mockBilling(page, workspace)
            await openPage(page, 'usage')
            await expect(page.getByRole('table')).toBeVisible()

            await page.getByTestId('date-filter').click()
            await expect(page.getByTestId('date-filter-last-30-days')).toBeVisible()
            await expect(page.getByTestId('date-filter-last-180-days')).toBeVisible()
            await expect(page.getByTestId('date-filter-all-time')).toHaveCount(0)
            await expect(page.getByTestId('date-filter-last-24-hours')).toHaveCount(0)
        })

        const answers = [
            {
                name: 'billing cancels the read',
                answer: refusal('usage_query_timeout', 'Billing cancelled the read.'),
                shows: 'This took too long to load. Select fewer projects or products, choose a shorter date range, or export it instead.',
            },
            {
                name: 'billing refuses the breakdown',
                answer: refusal('usage_breakdown_too_large', 'Billing refused the breakdown.'),
                shows: 'This breakdown is too large to show at once.',
            },
            {
                name: 'the range is over a year',
                answer: refusal(
                    'usage_date_range_too_long',
                    'The date range is longer than a year. Choose a range of at most a year.'
                ),
                shows: 'The date range is longer than a year. Choose a range of at most a year.',
            },
            {
                name: 'the period has no usage',
                answer: timeseries([]),
                shows: "We couldn't find any usage data for your current query.",
            },
        ]

        for (const { name, answer, shows } of answers) {
            test(`says what to do when ${name}, with no error toast`, async ({ page }) => {
                await mockBilling(page, workspace, { usage: () => answer })
                await openPage(page, 'usage')

                await expect(page.getByText(shows)).toBeVisible()
                await expect(page.getByRole('table')).toHaveCount(0)
                await expect(page.locator('.Toastify__toast--error')).toHaveCount(0)
            })
        }
    })

    test.describe('spend', () => {
        test('reads the period in one request and names the export for every project', async ({ page }) => {
            const reads = await mockBilling(page, workspace)
            await openPage(page, 'spend')

            const table = page.getByRole('table')
            await expect(table.getByText('Events', { exact: true })).toBeVisible()
            expect(reads.spend).toHaveLength(1)
            expect(reads.spend[0].get('breakdowns')).toBe('["type"]')
            expect(reads.spend[0].get('team_ids')).toBeNull()

            await openExportMenu(page)
            await expect(page.getByRole('menuitem', { name: 'All projects in this period' })).toBeVisible()
        })

        const answers = [
            {
                name: 'billing refuses the breakdown',
                answer: refusal('usage_breakdown_too_large', 'Billing refused the breakdown.'),
                shows: 'This breakdown is too large to show at once.',
            },
            {
                name: 'the period has no spend',
                answer: timeseries([]),
                shows: "We couldn't find any spend data for your current query.",
            },
        ]

        for (const { name, answer, shows } of answers) {
            test(`says what to do when ${name}, with no error toast`, async ({ page }) => {
                await mockBilling(page, workspace, { spend: () => answer })
                await openPage(page, 'spend')

                await expect(page.getByText(shows)).toBeVisible()
                await expect(page.locator('.Toastify__toast--error')).toHaveCount(0)
            })
        }
    })
})
