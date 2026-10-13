import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { APIRequestContext, APIResponse } from '@playwright/test'

/**
 * The usage and spend API through a running PostHog with a billing service behind it.
 *
 * Billing's own routes have their live suite in the billing repo. This one covers what PostHog adds
 * on top: the token it mints for a real organization, the parameters it validates before billing is
 * asked, the projects it lets a key see, the named errors it answers with, and the files it streams.
 *
 * CI has no billing behind the dev stack, so the suite only runs when asked:
 *
 *   RUN_BILLING_E2E=1 BASE_URL=http://localhost:8010 \
 *     pnpm --filter=@posthog/playwright exec playwright test products/billing/frontend/e2e/billing-usage-api.spec.ts
 *
 * The first half uses a fresh workspace, which billing creates a customer for on first sight. The
 * second half needs an organization whose projects have reported usage to billing, and skips without
 * a personal API key of one of its owners in BILLING_E2E_OWNER_KEY. BILLING_E2E_MEMBER_KEY, a plain
 * member's key, adds the member cases, with BILLING_E2E_MEMBER_HAS_READ_FLAG=1 when the member
 * usage-read flag is on for the organization.
 */

const CSV_HEADER = 'Product,Project,Project ID,Total'

function day(offset: number): string {
    const date = new Date()
    date.setUTCDate(date.getUTCDate() + offset)
    return date.toISOString().slice(0, 10)
}

const PERIOD = { start_date: day(-45), end_date: day(-1) }
const BY_PRODUCT = { ...PERIOD, breakdowns: '["type"]' }
const BY_PROJECT = { ...PERIOD, breakdowns: '["type","team"]' }

type Params = Record<string, string | number>
type Get = (path: string, params?: Params) => Promise<APIResponse>

function billing(request: APIRequestContext, key: string): Get {
    return (path, params = {}) =>
        request.get(`/api/billing/${path}`, { headers: { Authorization: `Bearer ${key}` }, params })
}

async function json(response: Promise<APIResponse>): Promise<any> {
    const answer = await response
    expect(answer.status(), await answer.text()).toBe(200)
    return answer.json()
}

function projectOf(series: { breakdown_value: string | string[] | null }): number | null {
    const value = series.breakdown_value
    const tail = Array.isArray(value) ? value[value.length - 1] : value
    return tail && /^\d+$/.test(tail) ? Number(tail) : null
}

async function expectCsv(response: Promise<APIResponse>, kind: 'usage' | 'spend'): Promise<string[]> {
    const file = await response
    expect(file.status(), await file.text()).toBe(200)
    expect(file.headers()['content-type']).toContain('text/csv')
    expect(file.headers()['content-disposition']).toBe(
        `attachment; filename="posthog_${kind}_${PERIOD.start_date}_${PERIOD.end_date}.csv"`
    )
    const lines = (await file.text()).trimEnd().split('\n')
    expect(lines[0].startsWith(CSV_HEADER)).toBe(true)
    return lines
}

test.describe('Billing usage and spend API', () => {
    test.skip(!process.env.RUN_BILLING_E2E, 'needs a billing service behind PostHog; set RUN_BILLING_E2E=1')

    test.describe('a fresh organization', () => {
        let workspace: PlaywrightWorkspaceSetupResult

        test.beforeAll(async ({ playwrightSetup }) => {
            workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        })

        test('every read answers for an organization billing has never seen', async ({ request }) => {
            const get = billing(request, workspace.personal_api_key)

            for (const kind of ['usage', 'spend']) {
                const answer = await json(get(`${kind}/`, BY_PRODUCT))
                expect(answer).toMatchObject({ results: [], team_id_options: [] })
                await expectCsv(get(`${kind}/export/`, BY_PRODUCT), kind as 'usage' | 'spend')
            }
            expect(await json(get('usage/team_options/'))).toEqual({ team_id_options: [] })

            const page = await json(get('usage/', { ...BY_PROJECT, page_size: 20 }))
            expect(page).toMatchObject({ results: [], total_count: 0, next: null })
        })

        test('parameters are validated before billing is asked, and a project outside the organization is refused', async ({
            request,
        }) => {
            const get = billing(request, workspace.personal_api_key)

            for (const params of [
                { ...PERIOD, team_ids: 'abc' },
                { ...PERIOD, team_ids: '["a"]' },
                { ...PERIOD, breakdowns: '["region"]' },
                { ...PERIOD, interval: 'hour' },
            ]) {
                expect((await get('usage/', params)).status(), JSON.stringify(params)).toBe(400)
            }

            const outside = await get('usage/', { ...PERIOD, team_ids: '[999999999]' })
            expect(outside.status()).toBe(403)
            expect((await outside.json()).detail).toBe('One or more requested projects are not in this organization.')
        })

        test("billing's refusal of a range over a year arrives as PostHog's own error", async ({ request }) => {
            const get = billing(request, workspace.personal_api_key)
            for (const kind of ['usage', 'spend']) {
                const refused = await get(`${kind}/`, { start_date: day(-400), end_date: day(-1) })
                expect(refused.status(), kind).toBe(400)
                expect(await refused.json()).toMatchObject({
                    code: 'usage_date_range_too_long',
                    detail: 'The date range is longer than a year. Choose a range of at most a year.',
                })
            }
        })

        test('a key that is not a key is refused before billing is called', async ({ request }) => {
            const response = await request.get('/api/billing/usage/', {
                headers: { Authorization: 'Bearer phx_not_a_key' },
                params: BY_PRODUCT,
            })
            expect(response.status()).toBe(401)
        })
    })

    test.describe('a seeded organization', () => {
        const ownerKey = process.env.BILLING_E2E_OWNER_KEY ?? ''
        const memberKey = process.env.BILLING_E2E_MEMBER_KEY ?? ''
        const memberHasReadFlag = process.env.BILLING_E2E_MEMBER_HAS_READ_FLAG === '1'

        test.skip(!ownerKey, 'needs BILLING_E2E_OWNER_KEY, an owner key of an organization with usage')

        test('the project options are the projects that reported, and a breakdown pages through every series once', async ({
            request,
        }) => {
            const get = billing(request, ownerKey)
            const options: number[] = (await json(get('usage/team_options/'))).team_id_options
            expect(options.length).toBeGreaterThan(0)
            expect(options).toEqual([...options].sort((a, b) => a - b))

            const first = await json(get('usage/', { ...BY_PROJECT, page_size: 7 }))
            const seen: string[] = []
            let page = first
            while (true) {
                seen.push(
                    ...page.results.map((series: { breakdown_value: string[] }) => series.breakdown_value.join('|'))
                )
                if (page.next === null) {
                    break
                }
                page = await json(get('usage/', { ...BY_PROJECT, page_size: 7, after: page.next }))
                expect(page.total_count).toBe(first.total_count)
            }
            expect(new Set(seen).size).toBe(seen.length)
            expect(seen.length).toBe(first.total_count)
        })

        test('a project selection narrows the series and the export to the selection', async ({ request }) => {
            const get = billing(request, ownerKey)
            const options: number[] = (await json(get('usage/team_options/'))).team_id_options
            const chosen = options.slice(0, 2)

            for (const kind of ['usage', 'spend']) {
                const answer = await json(get(`${kind}/`, { ...BY_PROJECT, team_ids: JSON.stringify(chosen) }))
                const projects = new Set(answer.results.map(projectOf).filter((id: number | null) => id !== null))
                expect(projects.size, kind).toBeGreaterThan(0)
                for (const project of projects) {
                    expect(chosen, kind).toContain(project)
                }
            }

            const lines = await expectCsv(
                get('usage/export/', { ...BY_PROJECT, team_ids: JSON.stringify(chosen) }),
                'usage'
            )
            expect(lines.length).toBeGreaterThan(1)
            for (const line of lines.slice(1)) {
                const projectId = line.split(',')[2]
                if (projectId) {
                    expect(chosen).toContain(Number(projectId))
                }
            }
        })

        test('a member reads what their role and flags allow', async ({ request }) => {
            test.skip(!memberKey, 'needs BILLING_E2E_MEMBER_KEY')
            const get = billing(request, memberKey)
            const withFlag = memberHasReadFlag ? 200 : 403
            for (const path of ['usage/', 'spend/', 'usage/team_options/']) {
                expect((await get(path, path === 'usage/team_options/' ? {} : BY_PRODUCT)).status(), path).toBe(
                    withFlag
                )
            }
        })
    })
})
