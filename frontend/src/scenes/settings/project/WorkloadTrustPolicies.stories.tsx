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
            claims: {
                repository: 'repository',
                repository_id: 'repository_id',
                ref: 'ref',
                environment: 'environment',
            },
        },
    ],
    unsupported: [
        {
            key: 'bitbucket_pipelines',
            name: 'Bitbucket Pipelines',
            reason: "The token's audience is fixed per workspace and cannot be set to this PostHog instance.",
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
                            repository: 'acme/web',
                            repository_id: '123456',
                            ref: 'refs/heads/main',
                            environment: 'production',
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
                            repository: 'acme/web',
                            repository_id: '123456',
                            ref: '',
                            environment: 'preview',
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
