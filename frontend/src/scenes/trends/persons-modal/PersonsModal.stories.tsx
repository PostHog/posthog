import { Meta, StoryFn } from '@storybook/react'

import { RawPropertiesTimelineResult } from 'lib/components/PropertiesTimeline/propertiesTimelineLogic'

import { useStorybookMocks } from '~/mocks/browser'

import { PersonsModal as PersonsModalComponent } from './PersonsModal'
import EXAMPLE_PERSONS_RESPONSE from './__mocks__/examplePersonsResponse.json'
import { ListActorsResponse } from './personsModalLogic'

const meta: Meta = {
    title: 'Scenes-App/Persons Modal',
}
export default meta

export const WithResults: StoryFn = () => {
    useStorybookMocks({
        get: {
            [EXAMPLE_PERSONS_RESPONSE.initial]: EXAMPLE_PERSONS_RESPONSE,
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
                            matched_recordings: ['1234567890'],
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
                            timestamp: '2022-12-08T00:00:00.000Z',
                            properties: {
                                name: 'Francisco Elliott',
                                email: 'mortgage2056@yandex.com',
                                $geoip_country_code: 'DE',
                            },
                            relevant_event_count: 155,
                        },
                        {
                            timestamp: '2022-12-12T00:00:00.000Z',
                            properties: {
                                name: 'Francisco Elliott',
                                email: 'mortgage2056@yandex.com',
                                $geoip_country_code: 'CN',
                            },
                            relevant_event_count: 13,
                        },
                    ],
                    crucial_property_keys: ['$geoip_country_code'],
                    effective_date_from: '2022-12-01T00:00:00.000+00:00',
                    effective_date_to: '2022-12-13T23:59:59.999999+00:00',
                } as RawPropertiesTimelineResult,
        },
    })

    return (
        <div className="flex max-h-200">
            <PersonsModalComponent title="Hello!" url={EXAMPLE_PERSONS_RESPONSE.initial} inline />
        </div>
    )
}

export const Empty: StoryFn = () => {
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
}

export const TimeoutError: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/persons/trends/*': (_, __, ctx) => [
                ctx.delay(200),
                ctx.status(512),
                ctx.json({
                    type: 'server_error',
                    detail: 'Estimated query execution time (34.5 seconds) is too long. Try reducing its scope by changing the time range.',
                }),
            ],
        },
    })

    return (
        <div className="flex max-h-200">
            <PersonsModalComponent title="Hello!" url="/api/projects/1/persons/trends/" inline />
        </div>
    )
}

export const ServerError: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/persons/trends/*': (_, __, ctx) => [
                ctx.delay(200),
                ctx.status(500),
                ctx.json({
                    type: 'server_error',
                    detail: 'There is nothing you can do to stop the impending catastrophe.',
                }),
            ],
        },
    })

    return (
        <div className="flex max-h-200">
            <PersonsModalComponent title="Hello!" url="/api/projects/1/persons/trends/" inline />
        </div>
    )
}

export const WithAllButtons: StoryFn = () => {
    useStorybookMocks({
        get: {
            [EXAMPLE_PERSONS_RESPONSE.initial]: EXAMPLE_PERSONS_RESPONSE,
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
                            matched_recordings: ['1234567890'],
                            relevant_event_count: 2,
                        },
                    ],
                    crucial_property_keys: ['$geoip_country_code'],
                    effective_date_from: '2022-12-01T00:00:00.000+00:00',
                    effective_date_to: '2022-12-13T23:59:59.999999+00:00',
                } as RawPropertiesTimelineResult,
        },
    })

    return (
        <div className="flex max-h-200">
            <PersonsModalComponent
                title="Page Reports - Persons on 12 Oct 2025"
                url={EXAMPLE_PERSONS_RESPONSE.initial}
                query={{
                    kind: 'InsightActorsQuery',
                    source: {
                        kind: 'TrendsQuery',
                        series: [{ kind: 'EventsNode', event: '$pageview' }],
                    },
                }}
                inline
            />
        </div>
    )
}
