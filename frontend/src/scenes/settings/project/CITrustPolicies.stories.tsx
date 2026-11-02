import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { CITrustPolicies } from './CITrustPolicies'

const meta: Meta = {
    title: 'Scenes-Other/Settings/Project/CI trust policies',
    component: CITrustPolicies,
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
    grantable_scopes: ['annotation:read', 'annotation:write', 'error_tracking:read', 'error_tracking:write'],
}

const createdBy = { id: 1, uuid: 'test-user', first_name: 'Test', email: 'test@example.com', hedgehog_config: null }

export const WithPolicies: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/ci_trust_policies/providers/': providers,
                '/api/projects/:team_id/ci_trust_policies/': {
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
        return <CITrustPolicies />
    },
}
