import { Meta } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { OAuthApps } from './OAuthApps'

const meta: Meta<typeof OAuthApps> = {
    title: 'Scenes-Other/Settings/Organization/OAuth Apps',
    component: OAuthApps,
}
export default meta

export const Empty = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/organizations/@current/oauth_applications/': {
                count: 0,
                next: null,
                previous: null,
                results: [],
            },
        },
    })
    return <OAuthApps />
}

export const WithApps = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/organizations/@current/oauth_applications/': {
                count: 2,
                next: null,
                previous: null,
                results: [
                    {
                        id: '1',
                        name: 'Acme Analytics',
                        client_id: 'abc123def456ghi789',
                        redirect_uris_list: ['https://acme.example.com/callback'],
                        is_verified: true,
                        created: '2025-11-01T10:30:00Z',
                        updated: '2025-11-01T10:30:00Z',
                    },
                    {
                        id: '2',
                        name: 'Internal Dashboard',
                        client_id: 'xyz987uvw654rst321',
                        redirect_uris_list: [
                            'https://dashboard.internal.dev/auth',
                            'http://localhost:3000/auth/callback',
                        ],
                        is_verified: false,
                        created: '2025-12-15T14:00:00Z',
                        updated: '2025-12-15T14:00:00Z',
                    },
                ],
            },
        },
    })
    return <OAuthApps />
}
