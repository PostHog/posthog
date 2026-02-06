import { Meta } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SessionDisplay } from './SessionDisplay'

const MOCK_SESSION_ID = '019577a4-4f44-7a43-8055-cd0e582109fa'

const mockSessionRow = [
    MOCK_SESSION_ID,
    'user-distinct-id-123',
    '2025-01-15T10:00:00Z',
    '2025-01-15T10:15:30Z',
    'https://app.example.com/dashboard',
    'https://app.example.com/settings',
    ['https://app.example.com/dashboard', 'https://app.example.com/reports', 'https://app.example.com/settings'],
    3,
    5,
    12,
    0,
    930,
    'Organic Search',
    false,
    'app.example.com',
    '/dashboard',
    'google',
    'summer-sale',
    'cpc',
    'google.com',
    'https://external.example.com/promo',
]

function mockQueryResponse(row: any[] | null): [number, any] {
    return [
        200,
        {
            columns: [],
            results: row ? [row] : [],
            hasMore: false,
        },
    ]
}

const meta: Meta<typeof SessionDisplay> = {
    title: 'Scenes/Sessions/SessionDisplay',
    component: SessionDisplay,
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': () => mockQueryResponse(mockSessionRow),
            },
            get: {
                '/api/environments/:team_id/session_recordings/': () => [
                    200,
                    {
                        results: [{ id: MOCK_SESSION_ID }],
                    },
                ],
            },
        }),
    ],
}
export default meta

export function Default(): JSX.Element {
    return <SessionDisplay sessionId={MOCK_SESSION_ID} />
}

export function Live(): JSX.Element {
    return <SessionDisplay sessionId={MOCK_SESSION_ID} isLive />
}

export function WithNoPopover(): JSX.Element {
    return <SessionDisplay sessionId={MOCK_SESSION_ID} noPopover />
}

export function WithNoLink(): JSX.Element {
    return <SessionDisplay sessionId={MOCK_SESSION_ID} noLink />
}

export function LiveWithNoPopover(): JSX.Element {
    return <SessionDisplay sessionId={MOCK_SESSION_ID} isLive noPopover />
}
