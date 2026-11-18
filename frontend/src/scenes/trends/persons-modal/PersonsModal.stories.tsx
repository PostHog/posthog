import { Meta, StoryObj } from '@storybook/react'
import { delay, HttpResponse } from 'msw'

import { useStorybookMocks } from '~/mocks/browser'
import { InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'

import type { PropertiesTimelineResponseApi } from 'products/persons/frontend/generated/api.schemas'

import EXAMPLE_PERSONS_RESPONSE from './__mocks__/examplePersonsResponse.json'
import EXAMPLE_SESSION_ACTORS_RESPONSE from './__mocks__/exampleSessionActorsResponse.json'
import { PersonsModal as PersonsModalComponent } from './PersonsModal'
import { ListActorsResponse } from './personsModalLogic'

const meta: Meta = {
    title: 'Scenes-App/Persons Modal',
}
export default meta

type Story = StoryObj<{}>

const EXAMPLE_TRENDS_ACTORS_QUERY: InsightActorsQuery = {
    kind: NodeKind.InsightActorsQuery,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
        interval: 'day',
        dateRange: { date_from: '2022-12-01', date_to: '2022-12-13' },
        breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'person' },
    },
    day: '2022-12-02',
    series: 0,
    includeRecordings: true,
}

const EXAMPLE_ACTORS_QUERY_RESPONSE = {
    columns: ['actor', 'event_count', 'matched_recordings'],
    results: EXAMPLE_PERSONS_RESPONSE.results[0].people.map((person) => [
        {
            id: person.uuid,
            distinct_ids: person.distinct_ids,
            is_identified: person.is_identified,
            properties: person.properties,
            created_at: person.created_at,
        },
        person.value_at_data_point,
        person.matched_recordings.map((session_id) => ({ session_id, events: [] })),
    ]),
    hasMore: false,
    limit: 100,
    offset: 0,
    missing_actors_count: 0,
}

export const WithResults: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': ({ params }) => [
                    200,
                    params.kind === NodeKind.ActorsQuery ? EXAMPLE_ACTORS_QUERY_RESPONSE : {},
                ],
                [`/api/projects/:team_id/persons/${EXAMPLE_PERSONS_RESPONSE.results[0].people[0].uuid}/properties_timeline/`]:
                    {
                        points: [
                            {
                                timestamp: '2022-12-02T00:00:00.000Z',
                                properties: {
                                    name: 'Francisco Elliott',
                                    email: 'mortgage2056@yandex.com',
                                    $geoip_country_code: 'US',
                                },
                                relevant_event_count: 2,
                            },
                            {
                                timestamp: '2022-12-02T08:00:00.000Z',
                                properties: {
                                    name: 'Francisco Elliott',
                                    email: 'mortgage2056@yandex.com',
                                    $geoip_country_code: 'PL',
                                },
                                relevant_event_count: 9,
                            },
                            {
                                timestamp: '2022-12-02T14:00:00.000Z',
                                properties: {
                                    name: 'Francisco Elliott',
                                    email: 'mortgage2056@yandex.com',
                                    $geoip_country_code: 'DE',
                                },
                                relevant_event_count: 3,
                            },
                        ],
                        crucial_property_keys: ['$geoip_country_code'],
                        effective_date_from: '2022-12-02T00:00:00+00:00',
                        effective_date_to: '2022-12-03T00:00:00+00:00',
                    } as PropertiesTimelineResponseApi,
            },
        })

        return (
            <div className="flex max-h-200">
                <PersonsModalComponent
                    title="Hello!"
                    query={EXAMPLE_TRENDS_ACTORS_QUERY}
                    additionalSelect={{ value_at_data_point: 'event_count', matched_recordings: 'matched_recordings' }}
                    inline
                />
            </div>
        )
    },
}

export const SessionActorsWithResults: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                [EXAMPLE_SESSION_ACTORS_RESPONSE.initial]: EXAMPLE_SESSION_ACTORS_RESPONSE,
            },
        })

        return (
            <div className="flex max-h-200">
                <PersonsModalComponent title="Session actors" url={EXAMPLE_SESSION_ACTORS_RESPONSE.initial} inline />
            </div>
        )
    },
}

export const Empty: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/persons/trends/*': {
                    results: [
                        {
                            people: [],
                            count: 0,
                        },
                    ],
                } as ListActorsResponse,
            },
        })

        return (
            <div className="flex max-h-200">
                <PersonsModalComponent title="Hello!" url="/api/projects/1/persons/trends/" inline />
            </div>
        )
    },
}

export const TimeoutError: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/persons/trends/*': async () => {
                    await delay(200)
                    return HttpResponse.json(
                        {
                            type: 'server_error',
                            detail: 'Estimated query execution time (34.5 seconds) is too long. Try reducing its scope by changing the time range.',
                        },
                        { status: 512 }
                    )
                },
            },
        })

        return (
            <div className="flex max-h-200">
                <PersonsModalComponent title="Hello!" url="/api/projects/1/persons/trends/" inline />
            </div>
        )
    },
}

export const ServerError: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/persons/trends/*': async () => {
                    await delay(200)
                    return HttpResponse.json(
                        {
                            type: 'server_error',
                            detail: 'There is nothing you can do to stop the impending catastrophe.',
                        },
                        { status: 500 }
                    )
                },
            },
        })

        return (
            <div className="flex max-h-200">
                <PersonsModalComponent title="Hello!" url="/api/projects/1/persons/trends/" inline />
            </div>
        )
    },
}
