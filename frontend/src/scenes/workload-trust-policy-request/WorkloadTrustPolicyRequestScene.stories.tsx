import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { WorkloadTrustPolicyRequestScene } from './WorkloadTrustPolicyRequestScene'

const meta: Meta = {
    title: 'Scenes-Other/Trusted workload request',
    component: WorkloadTrustPolicyRequestScene,
    parameters: {
        mockDate: '2026-10-02T10:00:00Z',
        layout: 'fullscreen',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<{}>

const policyRequest = {
    id: 'request-1',
    name: 'Production deploys',
    issuer: 'https://ci.example.com',
    provider: 'example_ci',
    provider_name: 'Example CI',
    subject_name: 'acme/web',
    subject: '123456',
    conditions: { ref: 'refs/heads/main' },
    claim_labels: {
        subject: 'Repository ID',
        subject_name: 'Repository',
        conditions: { ref: 'Branch or tag', environment: 'Environment' },
    },
    scopes: ['annotation:write', 'error_tracking:write', 'organization_member:write'],
    risky_scopes: {
        'organization_member:write': 'Invites and removes organization members and changes their roles.',
    },
    status: 'pending',
    approval_url: 'http://localhost:8010/project/1/workload-trust-policy-requests/request-1',
    requested_by: { id: 2, uuid: 'requester', first_name: 'Riley', last_name: 'Member', email: 'riley@example.com' },
    requested_via: 'hog',
    requested_via_verified: true,
    created_at: '2026-10-01T10:00:00Z',
    expires_at: '2026-10-08T10:00:00Z',
    resolved_by: null,
    resolved_at: null,
    policy_id: null,
}

function renderWith(overrides: Record<string, unknown>): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/workload_trust_policy_requests/:id/': { ...policyRequest, ...overrides },
        },
    })
    return <WorkloadTrustPolicyRequestScene id="request-1" />
}

export const PendingForAnAdmin: Story = {
    render: () => renderWith({ can_approve: true, approvers: [] }),
}

export const PendingForAMember: Story = {
    render: () =>
        renderWith({
            can_approve: false,
            approvers: ['Olive Owner', 'Ada Admin'],
            requested_via: 'Example agent',
            requested_via_verified: false,
        }),
}
