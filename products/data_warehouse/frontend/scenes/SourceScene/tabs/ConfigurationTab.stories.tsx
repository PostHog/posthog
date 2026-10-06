import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'

import { ConfigurationTab } from './ConfigurationTab'

const spotifySourceMock = {
    ...externalDataSourceResponseMock,
    source_type: 'Spotify',
    prefix: '',
    description: 'Team listening history',
    job_inputs: {},
    schemas: [],
    user_access_level: 'editor',
}

const availableSourcesMock = {
    Spotify: {
        name: 'Spotify',
        label: 'Spotify',
        category: 'Productivity',
        iconPath: '/static/services/spotify.png',
        fields: [],
        memberIntegrationKind: 'spotify',
        supportsColumnSelection: false,
        versions: ['v1'],
        defaultVersion: 'v1',
        deprecatedVersions: [],
    },
}

const teammate = (id: number, firstName: string, lastName: string): Record<string, unknown> => ({
    id,
    uuid: `0190a000-0000-0000-0000-00000000000${id}`,
    distinct_id: `teammate-${id}`,
    first_name: firstName,
    last_name: lastName,
    email: `${firstName.toLowerCase()}@example.com`,
})

const account = (id: number, displayName: string, createdBy: Record<string, unknown>): unknown => ({
    id,
    kind: 'spotify',
    display_name: displayName,
    config: { display_name: displayName },
    created_at: '2026-10-05T09:30:00Z',
    created_by: createdBy,
    errors: '',
})

type Story = StoryObj<typeof ConfigurationTab>
const meta: Meta<typeof ConfigurationTab> = {
    title: 'Scenes-App/Data Warehouse/Settings/Configuration',
    component: ConfigurationTab,
    args: {
        id: '123',
    },
    parameters: {
        mockDate: '2026-10-06',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
}

export default meta

// A source whose data comes from accounts that each project member connects themselves.
export const MemberAccountsSource: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': availableSourcesMock,
                '/api/environments/:team_id/external_data_sources/:id': spotifySourceMock,
                '/api/projects/:team_id/integrations/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        account(2, 'ada_listens', teammate(2, 'Ada', 'Okafor')),
                        account(3, 'grace.plays', teammate(3, 'Grace', 'Lindqvist')),
                    ],
                },
            },
        }),
    ],
}
