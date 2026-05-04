import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { PersonType } from '~/types'

import { notebookTestTemplate } from '../Notebook/__mocks__/notebook-template-for-snapshot'
import { NotebookNodeType, NotebookType } from '../types'

const PERSON_ID = '01234567-89ab-cdef-0123-456789abcdef'
const DISTINCT_ID = 'paul@posthog.com'

const personWithLocation: PersonType = {
    id: PERSON_ID,
    uuid: PERSON_ID,
    name: DISTINCT_ID,
    distinct_ids: [DISTINCT_ID],
    properties: {
        email: DISTINCT_ID,
        $geoip_latitude: 51.5074,
        $geoip_longitude: -0.1278,
        $geoip_city_name: 'London',
        $geoip_country_name: 'United Kingdom',
        $geoip_country_code: 'GB',
    },
    created_at: '2024-01-10T14:30:00Z',
    is_identified: true,
}

const personWithoutLocation: PersonType = {
    ...personWithLocation,
    properties: {
        email: DISTINCT_ID,
    },
}

function makeNotebook(shortId: string): NotebookType {
    return {
        ...notebookTestTemplate('Map node test', [
            {
                type: NotebookNodeType.Map,
                attrs: {
                    id: PERSON_ID,
                    distinctId: DISTINCT_ID,
                    nodeId: 'map-node-1',
                    title: 'Location',
                },
            },
        ]),
        short_id: shortId,
    }
}

const notebooksListMock = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: 'notebook-map-with-location',
            short_id: 'map-with-location',
            title: 'Map node test',
            created_at: '2024-01-01T00:00:00Z',
            last_modified_at: '2024-01-01T00:00:00Z',
        },
        {
            id: 'notebook-map-without-location',
            short_id: 'map-without-location',
            title: 'Map node test',
            created_at: '2024-01-01T00:00:00Z',
            last_modified_at: '2024-01-01T00:00:00Z',
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/Nodes/Map',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        testOptions: {
            snapshotBrowsers: [],
            waitForSelector: '.NotebookNode__content',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/notebooks/': notebooksListMock,
                'api/projects/:team_id/notebooks/map-with-location/': makeNotebook('map-with-location'),
                'api/projects/:team_id/notebooks/map-without-location/': makeNotebook('map-without-location'),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WithLocation: Story = {
    parameters: {
        pageUrl: urls.notebook('map-with-location'),
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/persons/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [personWithLocation],
                },
            },
        }),
    ],
}

export const WithoutLocation: Story = {
    parameters: {
        pageUrl: urls.notebook('map-without-location'),
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/persons/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [personWithoutLocation],
                },
            },
        }),
    ],
}
