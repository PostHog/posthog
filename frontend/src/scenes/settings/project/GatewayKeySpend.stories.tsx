import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { GatewayKeySpend } from './GatewayKeySpend'

const meta: Meta = {
    title: 'Scenes-Other/Settings/Project/Gateway key spend',
    component: GatewayKeySpend,
}
export default meta

type Story = StoryObj<{}>

const createdBy = { id: 1, uuid: 'test-user', first_name: 'Test', email: 'test@example.com', hedgehog_config: null }

// Every row shape: a key with spend, an idle key, an unscoped key, rolled-key spend, pre-attribution spend.
export const WithSpend: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/project_secret_api_keys/': {
                    count: 3,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'agent',
                            label: 'Support agent',
                            value: '',
                            mask_value: 'phs_...a1b2',
                            created_at: '2026-09-01T10:00:00Z',
                            created_by: createdBy,
                            last_used_at: '2026-10-14T21:45:00Z',
                            last_rolled_at: null,
                            scopes: ['llm_gateway:read'],
                            ai_credential: '1cf0cfd88962385d39a50f24133fd919',
                        },
                        {
                            id: 'idle',
                            label: 'Staging',
                            value: '',
                            mask_value: 'phs_...c3d4',
                            created_at: '2026-09-20T10:00:00Z',
                            created_by: createdBy,
                            last_used_at: null,
                            last_rolled_at: null,
                            scopes: ['llm_gateway:read'],
                            ai_credential: '9e6a0b3f5c2d4e1f8a7b6c5d4e3f2a1b',
                        },
                        {
                            id: 'flags',
                            label: 'Flags only',
                            value: '',
                            mask_value: 'phs_...e5f6',
                            created_at: '2026-08-01T10:00:00Z',
                            created_by: createdBy,
                            last_used_at: null,
                            last_rolled_at: null,
                            scopes: ['feature_flag:read'],
                            ai_credential: '0a1b2c3d4e5f60718293a4b5c6d7e8f9',
                        },
                    ],
                },
            },
            post: {
                '/api/environments/:team_id/query/HogQLQuery/': {
                    results: [
                        ['1cf0cfd88962385d39a50f24133fd919', 3234, 116.95],
                        ['fedcba9876543210fedcba9876543210', 42, 1.5],
                        [null, 11, 0.25],
                    ],
                },
            },
        })
        return <GatewayKeySpend />
    },
}
