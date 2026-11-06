import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { userLogic } from 'scenes/userLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { WorkloadTrustPolicies } from './WorkloadTrustPolicies'

const meta: Meta = {
    title: 'Scenes-Other/Settings/Project/Trusted workloads',
    component: WorkloadTrustPolicies,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<{}>

const ISSUER = 'https://ci.example.com'

const providers = {
    supported: [
        {
            key: 'example_ci',
            name: 'Example CI',
            issuer: ISSUER,
            docs_url: 'https://example.com/docs',
            subject_claim: { name: 'repository_id', label: 'Repository ID', help_text: '' },
            subject_name_claim: { name: 'repository', label: 'Repository', help_text: 'For example acme/web.' },
            condition_claims: [
                { name: 'ref', label: 'Branch or tag', help_text: 'For example refs/heads/main.' },
                { name: 'environment', label: 'Environment', help_text: '' },
            ],
        },
    ],
    grantable_scopes: [
        'annotation:read',
        'annotation:write',
        'error_tracking:read',
        'error_tracking:write',
        'organization_member:read',
        'organization_member:write',
    ],
    risky_scopes: {
        'organization_member:write': 'Invites and removes organization members and changes their roles.',
    },
}

const claimLabels = {
    subject: 'Repository ID',
    subject_name: 'Repository',
    conditions: { ref: 'Branch or tag', environment: 'Environment' },
}

const createdBy = { id: 1, uuid: 'test-user', first_name: 'Test', email: 'test@example.com', hedgehog_config: null }

export const WithPolicies: Story = {
    render: () => {
        // The section asks for a recent login on mount, so the story user has a fresh session before it renders.
        useState(() => {
            userLogic.mount()
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: '2099-01-01T00:00:00Z',
            })
        })
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/workload_trust_policies/providers/': providers,
                '/api/projects/:team_id/workload_trust_policies/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'deploys',
                            name: 'Production deploys',
                            issuer: ISSUER,
                            provider: 'example_ci',
                            subject_name: 'acme/web',
                            subject: '123456',
                            conditions: { environment: 'production', ref: 'refs/heads/main' },
                            claim_labels: claimLabels,
                            scopes: ['annotation:write', 'error_tracking:write'],
                            enabled: true,
                            created_by: createdBy,
                            created_at: '2026-10-01T10:00:00Z',
                            updated_at: '2026-10-01T10:00:00Z',
                        },
                        {
                            id: 'previews',
                            name: 'Preview builds',
                            issuer: ISSUER,
                            provider: 'example_ci',
                            subject_name: 'acme/web',
                            subject: '123456',
                            conditions: { environment: 'preview' },
                            claim_labels: claimLabels,
                            scopes: ['error_tracking:write'],
                            enabled: false,
                            created_by: createdBy,
                            created_at: '2026-10-02T10:00:00Z',
                            updated_at: '2026-10-02T10:00:00Z',
                        },
                    ],
                },
            },
        })
        return <WorkloadTrustPolicies />
    },
}
