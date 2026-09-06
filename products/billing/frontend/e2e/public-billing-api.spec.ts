import { expect, test } from '@playwright-utils/workspace-test-base'
import { APIRequestContext, APIResponse } from '@playwright/test'

/**
 * The organization billing API through a running PostHog with a billing service behind it.
 *
 * Billing's own routes have their own live suite in the billing repo. This one covers what PostHog
 * adds on top: the token it mints for a real organization, the shapes it serves, the parameters it
 * validates, the links it builds and the access it computes from roles and flags.
 *
 * CI has no billing behind the dev stack, so the suite only runs when asked:
 *
 *   RUN_BILLING_E2E=1 BASE_URL=http://localhost:8010 \
 *     pnpm --filter=@posthog/playwright exec playwright test products/billing/frontend/e2e/public-billing-api.spec.ts
 *
 * The first half uses a fresh workspace, which billing creates a customer for on first sight. The
 * second half needs an organization with seeded invoices and documents, from the billing repo's
 * dev_seed_invoices, and skips without these:
 *
 *   BILLING_E2E_ORG_ID, BILLING_E2E_OWNER_KEY, and optionally BILLING_E2E_MEMBER_KEY for a plain
 *   member of that organization, with BILLING_E2E_MEMBER_HAS_READ_FLAG=1 when the member usage-read
 *   flag is on for it.
 */

const SERIES = { start_date: '2026-08-01', end_date: '2026-09-05', breakdowns: '["type"]' }

function billing(request: APIRequestContext, organizationId: string, key: string) {
    const base = `/api/organizations/${organizationId}/billing`
    return (path: string, params: Record<string, string | number> = {}): Promise<APIResponse> =>
        request.get(`${base}/${path}`, { headers: { Authorization: `Bearer ${key}` }, params })
}

test.describe('Organization billing API', () => {
    test.skip(!process.env.RUN_BILLING_E2E, 'needs a billing service behind PostHog; set RUN_BILLING_E2E=1')

    test.describe('a fresh organization', () => {
        test('every read answers for a customer billing has never seen', async ({ request, playwrightSetup }) => {
            const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
            const get = billing(request, workspace.organization_id, workspace.personal_api_key)

            const subscription = await (await get('subscription/')).json()
            expect(subscription).toMatchObject({ has_active_subscription: false })
            expect(subscription).toHaveProperty('billing_period')
            expect(subscription).not.toHaveProperty('status')

            const features = await (await get('features/')).json()
            expect(Array.isArray(features.available_product_features)).toBe(true)

            const products = await (await get('products/')).json()
            expect(products.results.length).toBeGreaterThan(0)
            for (const product of products.results) {
                expect(product.kind).toBe('product')
                expect(product).toHaveProperty('key')
                expect(product).not.toHaveProperty('type')
                for (const addon of product.addons) {
                    expect(addon.kind).toBe('addon')
                }
            }
            expect((await (await get('products/product_analytics/')).json()).key).toBe('product_analytics')

            const usage = await (await get('usage/')).json()
            expect(usage).toHaveProperty('usage_summary')
            expect(usage).toHaveProperty('usage_reported_through')
            expect(usage).not.toHaveProperty('customer_id')

            for (const path of ['spend/', 'forecast/', 'limits/']) {
                expect((await get(path)).status(), path).toBe(200)
            }
            for (const kind of ['usage', 'spend']) {
                const series = await (await get(`${kind}/timeseries/`, SERIES)).json()
                expect(series).toMatchObject({ count: expect.any(Number), results: expect.any(Array) })
            }

            const invoices = await (await get('invoices/')).json()
            expect(invoices).toEqual({ next: null, previous: null, results: [] })
        })

        test('invoice parameters are validated before billing is asked', async ({ request, playwrightSetup }) => {
            const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
            const get = billing(request, workspace.organization_id, workspace.personal_api_key)
            for (const params of [{ limit: 'abc' }, { limit: 0 }, { status: 'draft' }]) {
                expect((await get('invoices/', params)).status(), JSON.stringify(params)).toBe(400)
            }
            expect((await get('invoices/', { cursor: 'nonsense' })).status()).toBe(400)
            expect((await get('invoices/in_nope/content/')).status()).toBe(404)
        })

        test('a key without the billing scope is refused before billing is called', async ({
            request,
            playwrightSetup,
        }) => {
            const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
            const response = await request.get(
                `/api/organizations/${workspace.organization_id}/billing/subscription/`,
                {
                    headers: { Authorization: 'Bearer phx_not_a_key' },
                }
            )
            expect(response.status()).toBe(401)
        })
    })

    test.describe('a seeded organization', () => {
        const orgId = process.env.BILLING_E2E_ORG_ID ?? ''
        const ownerKey = process.env.BILLING_E2E_OWNER_KEY ?? ''
        const memberKey = process.env.BILLING_E2E_MEMBER_KEY ?? ''
        const memberHasReadFlag = process.env.BILLING_E2E_MEMBER_HAS_READ_FLAG === '1'

        test.skip(!(orgId && ownerKey), 'needs BILLING_E2E_ORG_ID and BILLING_E2E_OWNER_KEY')

        test('cursor links keep the page size and filter, and every invoice is listed once', async ({ request }) => {
            const get = billing(request, orgId, ownerKey)
            const everything = (await (await get('invoices/')).json()).results.map((row: { id: string }) => row.id)
            expect(everything.length).toBeGreaterThan(1)

            let page = await (await get('invoices/', { limit: 1, status: 'paid' })).json()
            expect(page.previous).toBeNull()
            const seen: string[] = []
            while (true) {
                seen.push(...page.results.map((row: { id: string }) => row.id))
                if (page.next === null) {
                    break
                }
                expect(page.next).toContain('limit=1')
                expect(page.next).toContain('status=paid')
                page = await (await request.get(page.next, { headers: { Authorization: `Bearer ${ownerKey}` } })).json()
            }
            const paid = (await (await get('invoices/', { status: 'paid' })).json()).results.map(
                (row: { id: string }) => row.id
            )
            expect(seen).toEqual(paid)
            expect(new Set(seen).size).toBe(seen.length)
        })

        test('an invoice document downloads as a PDF and the provider link never appears', async ({ request }) => {
            const get = billing(request, orgId, ownerKey)
            const list = await get('invoices/')
            const text = await list.text()
            expect(text).not.toContain('invoice_pdf')
            expect(text).not.toContain('pdf_url')
            const first = (await list.json()).results[0]
            const document = await get(`invoices/${first.id}/content/`)
            expect(document.status()).toBe(200)
            expect(document.headers()['content-type']).toBe('application/pdf')
            expect(document.headers()['content-disposition']).toBe(`attachment; filename="${first.id}.pdf"`)
            expect((await document.body()).subarray(0, 4).toString()).toBe('%PDF')
        })

        test('a member reads what their role and flags allow', async ({ request }) => {
            test.skip(!memberKey, 'needs BILLING_E2E_MEMBER_KEY')
            const get = billing(request, orgId, memberKey)
            for (const path of ['subscription/', 'features/', 'products/', 'usage/']) {
                expect((await get(path)).status(), path).toBe(200)
            }
            for (const path of ['forecast/', 'invoices/', 'limits/']) {
                expect((await get(path)).status(), path).toBe(403)
            }
            const withFlag = memberHasReadFlag ? 200 : 403
            expect((await get('spend/')).status()).toBe(withFlag)
            expect((await get('usage/timeseries/', SERIES)).status()).toBe(withFlag)
        })
    })
})
