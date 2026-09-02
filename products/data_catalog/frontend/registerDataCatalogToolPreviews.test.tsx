import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { lookupToolRenderer } from 'products/posthog_ai/frontend/api/tools'
import type { PermissionRequestRecord } from 'products/posthog_ai/frontend/api/types'

import { certificationsLogic } from './certificationsLogic'
import { dataCatalogCertificationsList } from './generated/api'
import type {
    DataCatalogCertificationApi,
    DataCatalogMetricApi,
    DataCatalogRelationshipProposalApi,
} from './generated/api.schemas'
import { certificationPreview, metricApprovePreview, relationshipPreview } from './registerDataCatalogToolPreviews'

jest.mock('./generated/api', () => ({
    dataCatalogCertificationsList: jest.fn(),
    dataCatalogCertificationsCreate: jest.fn(),
    dataCatalogCertificationsCertifyCreate: jest.fn(),
    dataCatalogCertificationsDeprecateCreate: jest.fn(),
    dataCatalogCertificationsDestroy: jest.fn(),
}))

jest.mock('scenes/data-management/database/databaseTableListLogic', () => ({
    databaseTableListLogic: { loadDatabase: jest.fn(() => ({ type: 'load database (mock)' })) },
}))

function buildCertification(overrides: Partial<DataCatalogCertificationApi> = {}): DataCatalogCertificationApi {
    return {
        id: 'cert-1',
        target_name: 'stripe_charges',
        target_type: 'table',
        status: 'proposed',
        notes: '',
        ...overrides,
    } as DataCatalogCertificationApi
}

function buildMetric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'weekly_active_users',
        description: 'People with at least one event in the week.',
        status: 'proposed',
        definition_kind: 'TrendsQuery',
        is_drifted: false,
        ...overrides,
    } as DataCatalogMetricApi
}

function buildProposal(
    overrides: Partial<DataCatalogRelationshipProposalApi> = {}
): DataCatalogRelationshipProposalApi {
    return {
        id: 'proposal-1',
        source_table_name: 'events',
        source_table_key: 'person_id',
        joining_table_name: 'persons',
        joining_table_key: 'id',
        field_name: 'person',
        status: 'proposed',
        confidence: 0.9,
        reasoning: 'Keys match on a sample.',
        ...overrides,
    } as DataCatalogRelationshipProposalApi
}

describe('data catalog approval previews', () => {
    afterEach(() => cleanup())

    it.each([
        ['certified' as const, 'proposed → certified'],
        ['deprecated' as const, 'proposed → deprecated'],
    ])('names the source and the %s lifecycle step', (decision, change) => {
        render(<>{certificationPreview({ id: 'cert-1' }, [buildCertification()], decision)}</>)
        expect(screen.getByText('stripe_charges')).toBeInTheDocument()
        expect(screen.getByText(change)).toBeInTheDocument()
    })

    // Without this the approver reads a certification UUID they cannot map to a table or view.
    it.each([
        ['an id the scene has not loaded', { id: 'cert-missing' }],
        ['no id at all', {}],
    ])('falls back to the raw payload for %s', (_name, input) => {
        expect(certificationPreview(input, [buildCertification()], 'certified')).toBeNull()
    })

    it('names the metric and warns that drift blocks approval', () => {
        render(
            <>
                {metricApprovePreview({ name: 'weekly_active_users' }, [
                    buildMetric({ display_name: 'Weekly active users', is_drifted: true }),
                ])}
            </>
        )
        expect(screen.getByText('Weekly active users')).toBeInTheDocument()
        expect(screen.getByText('weekly_active_users')).toBeInTheDocument()
        expect(screen.getByText('proposed → approved')).toBeInTheDocument()
        expect(screen.getByText(/no longer matches its source insight/)).toBeInTheDocument()
    })

    it('names both sides of the join and the rejection reason a relationship decision settles', () => {
        // The reject call persists rejection_reason forever, so the card must surface the note the
        // approver is about to commit rather than hiding it behind the suppressed raw payload.
        render(
            <>
                {relationshipPreview(
                    { id: 'proposal-1', rejection_reason: 'Keys collide on null person ids.' },
                    [buildProposal()],
                    'rejected'
                )}
            </>
        )
        expect(screen.getByText('events.person_id → persons.id')).toBeInTheDocument()
        expect(screen.getByText('proposed → rejected')).toBeInTheDocument()
        expect(screen.getByText('events.person')).toBeInTheDocument()
        expect(screen.getByText('90%')).toBeInTheDocument()
        expect(screen.getByText('Keys collide on null person ids.')).toBeInTheDocument()
    })
})

// The whole path an approval takes: the agent's exec command names the sub-tool, the registry resolves
// it to the preview registered by importing this module, and the preview reads the mounted scene logic.
// A renamed tool key or a changed arg name breaks that chain and puts the approver back on a bare UUID.
describe('data catalog approval preview registration', () => {
    afterEach(() => cleanup())

    it('renders the certification behind a certify approval request', async () => {
        ;(dataCatalogCertificationsList as jest.Mock).mockResolvedValue({ results: [buildCertification()] })
        initKeaTests()
        certificationsLogic().mount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        const request = {
            requestId: 'req-1',
            toolCallId: 'tc-1',
            toolName: 'mcp__posthog__exec',
            options: [],
            rawToolCall: {
                toolCallId: 'tc-1',
                rawServerName: 'posthog',
                rawToolName: 'exec',
                input: { command: 'call data-catalog-certification-certify {"id":"cert-1"}' },
                status: 'pending',
                contentBlocks: [],
            },
        } as unknown as PermissionRequestRecord

        const entry = lookupToolRenderer('data-catalog-certification-certify', true)
        render(<>{entry.renderPermissionPreview?.(request)}</>)
        expect(screen.getByText('stripe_charges')).toBeInTheDocument()
        expect(screen.getByText('proposed → certified')).toBeInTheDocument()
    })

    // An imported MCP server can expose a tool with the same bare name; its payload keeps the raw JSON.
    it('withholds the preview from a call that did not come through the PostHog server', () => {
        expect(lookupToolRenderer('data-catalog-certification-certify', false).renderPermissionPreview).toBeUndefined()
    })
})
