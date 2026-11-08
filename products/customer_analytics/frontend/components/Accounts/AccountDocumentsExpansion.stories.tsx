import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type {
    AccountDocumentApi,
    AccountLegalDocumentApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountDocumentsExpansion } from './AccountDocumentsExpansion'

const DOCUMENTS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/documents/'
const LEGAL_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/documents/legal/'

const documents: AccountDocumentApi[] = [
    {
        id: '11111111-2222-4333-8444-555555555551',
        account_id: '11111111-2222-4333-8444-555555555550',
        document_type: 'order_form',
        title: 'Example Co order form, 12 months',
        status: 'sent',
        source: 'pandadoc',
        external_url: '',
        pandadoc_document_id: 'ExampleDocumentId0001',
        pandadoc_status: 'document.sent',
        pandadoc_synced_at: '2026-06-01T10:00:00Z',
        pandadoc_url: 'https://app.pandadoc.com/a/#/documents/ExampleDocumentId0001',
        effective_date: '2026-07-01',
        end_date: '2027-06-30',
        amount: '105000.00',
        created_by_id: 1,
        created_at: '2026-06-01T10:00:00Z',
        updated_at: '2026-06-01T10:00:00Z',
    },
    {
        id: '11111111-2222-4333-8444-555555555552',
        account_id: '11111111-2222-4333-8444-555555555550',
        document_type: 'security_questionnaire',
        title: 'Security questionnaire',
        status: 'signed',
        source: 'link',
        external_url: 'https://docs.example.com/security-questionnaire',
        pandadoc_document_id: '',
        pandadoc_status: '',
        pandadoc_synced_at: null,
        pandadoc_url: null,
        effective_date: null,
        end_date: null,
        amount: null,
        created_by_id: 1,
        created_at: '2026-05-20T09:30:00Z',
        updated_at: '2026-05-20T09:30:00Z',
    },
]

const legalDocuments: AccountLegalDocumentApi[] = [
    {
        id: '11111111-2222-4333-8444-555555555553',
        document_type: 'DPA',
        status: 'signed',
        company_name: 'Example Co',
        representative_email: 'legal@example.com',
        created_at: '2026-05-10T08:00:00Z',
        download_available: true,
    },
    {
        id: '11111111-2222-4333-8444-555555555554',
        document_type: 'BAA',
        status: 'submitted_for_signature',
        company_name: 'Example Co',
        representative_email: 'legal@example.com',
        created_at: '2026-05-28T08:00:00Z',
        download_available: false,
    },
]

const meta: Meta<typeof AccountDocumentsExpansion> = {
    title: 'Customer Analytics/Account views/Documents',
    component: AccountDocumentsExpansion,
    args: { accountId: '11111111-2222-4333-8444-555555555550', embedded: false },
    parameters: {
        mockDate: '2026-06-02T12:00:00Z',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-documents-table"]' },
    },
    decorators: [
        (Story, { parameters }) => (
            <div className={parameters.narrow ? 'w-128 p-2' : 'w-192 p-2'}>
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AccountDocumentsExpansion>

const populatedMocks = mswDecorator({ get: { [DOCUMENTS_ENDPOINT]: documents, [LEGAL_ENDPOINT]: legalDocuments } })

export const Documents: Story = { decorators: [populatedMocks] }

export const Narrow: Story = { parameters: { narrow: true }, decorators: [populatedMocks] }

export const Empty: Story = {
    parameters: { testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-documents-empty"]' } },
    decorators: [mswDecorator({ get: { [DOCUMENTS_ENDPOINT]: [], [LEGAL_ENDPOINT]: [] } })],
}

export const Loading: Story = {
    parameters: {
        testOptions: {
            snapshotBrowsers: [],
            waitForSelector: '[data-attr="account-documents-loading"]',
            waitForLoadersToDisappear: false,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [DOCUMENTS_ENDPOINT]: async () => new Promise<never>(() => {}),
                [LEGAL_ENDPOINT]: async () => new Promise<never>(() => {}),
            },
        }),
    ],
}

export const Error: Story = {
    parameters: { testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-documents-error"]' } },
    decorators: [
        mswDecorator({ get: { [DOCUMENTS_ENDPOINT]: [500, { detail: 'Request failed' }], [LEGAL_ENDPOINT]: [] } }),
    ],
}
