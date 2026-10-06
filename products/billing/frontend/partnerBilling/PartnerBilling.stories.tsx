import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'

import type {
    PartnerPayerApplicationApi,
    PartnerPayerInvoiceApi,
    PartnerPayerOrganizationApi,
    PartnerPayerSettlementApi,
    PartnerPayerSettlementInvoiceApi,
    PartnerPayerStatusApi,
    PatchedPartnerPayerAdminUpdateApi,
    PatchedPartnerPayerOrganizationLimitsApi,
} from '../generated/api.schemas'
import { PartnerBilling } from './PartnerBilling'

const APPLICATION: PartnerPayerApplicationApi = {
    id: '0192d7c4-5b6e-7000-8000-00000000a001',
    name: 'Example Site Builder',
    logo_uri: null,
}

const PAYER: PartnerPayerStatusApi = {
    name: 'Example Site Builder Inc.',
    billing_enabled: true,
    has_payment_method: true,
    billing_details: {
        address: {
            line1: '1 Example Street',
            line2: 'Suite 100',
            city: 'Springfield',
            state: 'CA',
            postal_code: '90000',
            country: 'US',
        },
        tax_ids: [{ type: 'us_ein', value: '00-0000000' }],
    },
    organization_count: 3,
    webhook: { url: 'https://hooks.example.com/posthog/billing', secret_created_at: '2026-09-01T10:00:00Z' },
    past_due: false,
    spend: { month_to_date_usd: '1840.25', alert_usd: '2500.00', cap_usd: '5000.00', capped: false },
    default_limits_usd: { product_analytics: 500, session_replay: 250 },
}

const ORGANIZATIONS: PartnerPayerOrganizationApi[] = [
    {
        organization_id: '0192d7c4-5b6e-7000-8000-00000000c001',
        name: 'Example Bakery',
        linked_at: '2026-06-12T09:30:00Z',
        detached_at: null,
        custom_limits_usd: { product_analytics: 800, session_replay: null },
    },
    {
        organization_id: '0192d7c4-5b6e-7000-8000-00000000c002',
        name: 'Example Bike Repair',
        linked_at: '2026-08-03T14:00:00Z',
        detached_at: null,
        custom_limits_usd: {},
    },
    {
        organization_id: '0192d7c4-5b6e-7000-8000-00000000c003',
        name: 'Example Dental Clinic',
        linked_at: '2026-04-20T08:15:00Z',
        detached_at: '2026-09-15T12:00:00Z',
        custom_limits_usd: { session_replay: 100 },
    },
]

const INVOICES: PartnerPayerInvoiceApi[] = [
    {
        invoice_id: 'in_example_0003',
        organization_id: ORGANIZATIONS[0].organization_id,
        period_start: '2026-09-01T00:00:00Z',
        period_end: '2026-10-01T00:00:00Z',
        amount_cents: 112050,
        currency: 'USD',
        status: 'open',
        settlement_id: 'stl_example_2026_09',
        pdf_url: 'https://files.example.com/invoices/in_example_0003.pdf',
    },
    {
        invoice_id: 'in_example_0002',
        organization_id: ORGANIZATIONS[1].organization_id,
        period_start: '2026-09-01T00:00:00Z',
        period_end: '2026-10-01T00:00:00Z',
        amount_cents: 41975,
        currency: 'USD',
        status: 'open',
        settlement_id: 'stl_example_2026_09',
        pdf_url: 'https://files.example.com/invoices/in_example_0002.pdf',
    },
    {
        invoice_id: 'in_example_0001',
        organization_id: ORGANIZATIONS[2].organization_id,
        period_start: '2026-08-01T00:00:00Z',
        period_end: '2026-09-01T00:00:00Z',
        amount_cents: 98000,
        currency: 'USD',
        status: 'paid',
        settlement_id: 'stl_example_2026_08',
        pdf_url: null,
    },
]

const PAID_SETTLEMENT: PartnerPayerSettlementApi = {
    settlement_id: 'stl_example_2026_08',
    period_start: '2026-08-01T00:00:00Z',
    period_end: '2026-09-01T00:00:00Z',
    amount_cents: 98000,
    currency: 'USD',
    status: 'paid',
    attempt_count: 1,
    next_attempt_at: null,
    paid_at: '2026-09-02T06:00:00Z',
}

const PROCESSING_SETTLEMENT: PartnerPayerSettlementApi = {
    settlement_id: 'stl_example_2026_09',
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    amount_cents: 154025,
    currency: 'USD',
    status: 'processing',
    attempt_count: 1,
    next_attempt_at: null,
    paid_at: null,
}

const FAILED_SETTLEMENT: PartnerPayerSettlementApi = {
    ...PROCESSING_SETTLEMENT,
    status: 'failed',
    attempt_count: 2,
    next_attempt_at: '2026-10-08T06:00:00Z',
}

const SETTLEMENT_INVOICES: PartnerPayerSettlementInvoiceApi[] = [
    { ...INVOICES[0], charged_cents: 112050 },
    { ...INVOICES[1], amount_cents: null, charged_cents: 41975 },
]

// Billing drops a default set to null, but keeps an organization's own null as no limit.
function withDefaultLimitChanges(
    limits: Record<string, number | null> | undefined,
    changes: Record<string, number | null> | undefined
): Record<string, number | null> {
    const updated = { ...limits, ...changes }
    return Object.fromEntries(Object.entries(updated).filter(([, limit]) => limit !== null))
}

function partnerBillingMocks(payer: PartnerPayerStatusApi, settlements: PartnerPayerSettlementApi[]): Mocks {
    const [latestSettlement] = settlements
    return {
        get: {
            '/api/organizations/:organization_id/partner_billing/': [APPLICATION],
            '/api/organizations/:organization_id/partner_billing/:id/': payer,
            '/api/organizations/:organization_id/partner_billing/:id/organizations/': {
                count: ORGANIZATIONS.length,
                results: ORGANIZATIONS,
            },
            '/api/organizations/:organization_id/partner_billing/:id/invoices/': ({ request }) => {
                const filters = new URL(request.url).searchParams
                const invoices = INVOICES.filter(
                    (invoice) =>
                        [null, invoice.organization_id].includes(filters.get('organization_id')) &&
                        [null, invoice.status].includes(filters.get('status'))
                )
                return [200, { count: invoices.length, results: invoices }]
            },
            '/api/organizations/:organization_id/partner_billing/:id/settlements/': {
                count: settlements.length,
                results: settlements,
            },
            '/api/organizations/:organization_id/partner_billing/:id/settlements/:settlement_id/': latestSettlement
                ? {
                      ...latestSettlement,
                      invoices: SETTLEMENT_INVOICES.filter(
                          (invoice) => invoice.settlement_id === latestSettlement.settlement_id
                      ),
                  }
                : [404, { detail: 'Billing has no record of this.' }],
        },
        post: {
            '/api/organizations/:organization_id/partner_billing/:id/webhook_secret/': {
                secret: 'whsec_ZXhhbXBsZS1zdG9yeWJvb2stc2VjcmV0',
                created_at: '2026-10-04T12:00:00Z',
            },
            '/api/organizations/:organization_id/partner_billing/:id/test_event/': { event_id: 'evt_example_0001' },
            '/api/organizations/:organization_id/partner_billing/:id/settlements/:settlement_id/retry/': {
                ...latestSettlement,
                status: 'paid',
                next_attempt_at: null,
                paid_at: '2026-10-05T12:00:00Z',
            },
        },
        patch: {
            '/api/organizations/:organization_id/partner_billing/:id/': async ({ request }) => {
                const changes = (await request.json()) as PatchedPartnerPayerAdminUpdateApi
                return [
                    200,
                    {
                        ...payer,
                        webhook: { ...payer.webhook, url: changes.webhook_url ?? payer.webhook?.url },
                        spend: payer.spend && {
                            ...payer.spend,
                            alert_usd: 'spend_alert_usd' in changes ? changes.spend_alert_usd : payer.spend.alert_usd,
                            cap_usd: 'spend_cap_usd' in changes ? changes.spend_cap_usd : payer.spend.cap_usd,
                        },
                        default_limits_usd: withDefaultLimitChanges(
                            payer.default_limits_usd,
                            changes.default_limits_usd
                        ),
                    },
                ]
            },
            '/api/organizations/:organization_id/partner_billing/:id/organizations/:customer_organization_id/limits/':
                async ({ request, params }) => {
                    const changes = (await request.json()) as PatchedPartnerPayerOrganizationLimitsApi
                    const organization =
                        ORGANIZATIONS.find(
                            ({ organization_id }) => organization_id === params.customer_organization_id
                        ) ?? ORGANIZATIONS[0]
                    return [
                        200,
                        {
                            ...organization,
                            custom_limits_usd: { ...organization.custom_limits_usd, ...changes.custom_limits_usd },
                        },
                    ]
                },
        },
    }
}

const meta: Meta<typeof PartnerBilling> = {
    title: 'Scenes-Other/Settings/Organization/Partner billing',
    component: PartnerBilling,
    parameters: { mockDate: '2026-10-05' },
}
export default meta

type Story = StoryObj<typeof PartnerBilling>

export const BillingNotOnYet: Story = {
    decorators: [
        mswDecorator(partnerBillingMocks({ name: PAYER.name, billing_enabled: false }, [])),
        (Story) => (
            <div className="w-200">
                <Story />
            </div>
        ),
    ],
}

export const BillingOn: Story = {
    decorators: [mswDecorator(partnerBillingMocks(PAYER, [PROCESSING_SETTLEMENT, PAID_SETTLEMENT]))],
}

export const BillingOnBeforeSpendReporting: Story = {
    decorators: [
        mswDecorator(partnerBillingMocks({ ...PAYER, spend: undefined }, [PROCESSING_SETTLEMENT, PAID_SETTLEMENT])),
    ],
}

export const FailedSettlement: Story = {
    decorators: [mswDecorator(partnerBillingMocks({ ...PAYER, past_due: true }, [FAILED_SETTLEMENT, PAID_SETTLEMENT]))],
}
