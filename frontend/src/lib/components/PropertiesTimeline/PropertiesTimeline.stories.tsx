import { Meta } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, PersonActorType } from '~/types'

import type { PropertiesTimelineResponseApi } from 'products/persons/frontend/generated/api.schemas'

import { PropertiesTimeline } from '.'
import { PropertiesTimelineProps } from './propertiesTimelineLogic'

const meta: Meta<PropertiesTimelineProps> = {
    title: 'Components/Properties Timeline',
    component: PropertiesTimeline,
}
export default meta

const EXAMPLE_PERSON: Omit<PersonActorType, 'id' | 'uuid'> = {
    type: 'person',
    distinct_ids: ['one'],
    is_identified: true,
    properties: {},
    created_at: '2021-01-01T00:00:00.000Z',
    matched_recordings: [],
    value_at_data_point: null,
}

const EXAMPLE_QUERY: InsightActorsQuery = {
    kind: NodeKind.InsightActorsQuery,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        dateRange: { date_from: '2021-01-01', date_to: '2021-06-01' },
        trendsFilter: { display: ChartDisplayType.BoldNumber },
    },
}

export function MultiplePointsForOnePersonProperty(): JSX.Element {
    const examplePerson: PersonActorType = { ...EXAMPLE_PERSON, id: '012e89b5-4239-4319-8ae4-d3cae2f5deb1' }
    useStorybookMocks({
        post: {
            [`/api/projects/:team_id/persons/${examplePerson.id}/properties_timeline/`]: {
                points: [
                    {
                        timestamp: '2021-01-01T00:00:00.000Z',
                        properties: {
                            hobby: 'hiking',
                            name: 'Perry',
                        },
                        relevant_event_count: 3,
                    },
                    {
                        timestamp: '2021-01-17T00:00:00.000Z',
                        properties: {
                            hobby: 'hiking',
                            name: 'Jerry',
                        },
                        relevant_event_count: 3,
                    },
                    {
                        timestamp: '2021-01-18T08:00:00.000Z',
                        properties: {
                            hobby: 'sailing',
                            name: 'Kerry',
                        },
                        relevant_event_count: 3,
                    },
                    {
                        timestamp: '2021-03-01T00:00:00.000Z',
                        properties: {
                            hobby: 'hiking',
                            name: 'Terry',
                        },
                        relevant_event_count: 1,
                    },
                ],
                crucial_property_keys: ['name'],
                effective_date_from: '2021-01-01T00:00:00.000000+00:00',
                effective_date_to: '2021-06-01T23:59:59.999999+00:00',
            } as PropertiesTimelineResponseApi,
        },
    })

    return (
        <div className="border rounded w-120">
            <PropertiesTimeline actor={examplePerson} query={EXAMPLE_QUERY} />
        </div>
    )
}

export function OnePointForOnePersonProperty(): JSX.Element {
    const examplePerson: PersonActorType = { ...EXAMPLE_PERSON, id: '012e89b5-4239-4319-8ae4-d3cae2f5deb2' }
    useStorybookMocks({
        post: {
            [`/api/projects/:team_id/persons/${examplePerson.id}/properties_timeline/`]: {
                points: [
                    {
                        timestamp: '2021-05-01T00:00:00.000Z',
                        properties: {
                            hobby: 'reading',
                            name: 'Gerry',
                        },
                        relevant_event_count: 997,
                    },
                ],
                crucial_property_keys: ['name'],
                effective_date_from: '2021-01-01T00:00:00.000000+00:00',
                effective_date_to: '2021-06-01T23:59:59.999999+00:00',
            } as PropertiesTimelineResponseApi,
        },
    })

    return (
        <div className="border rounded w-120">
            <PropertiesTimeline actor={examplePerson} query={EXAMPLE_QUERY} />
        </div>
    )
}

export function NoPointsForNoPersonProperties(): JSX.Element {
    const examplePerson: PersonActorType = { ...EXAMPLE_PERSON, id: '012e89b5-4239-4319-8ae4-d3cae2f5deb3' }
    useStorybookMocks({
        post: {
            [`/api/projects/:team_id/persons/${examplePerson.id}/properties_timeline/`]: {
                points: [
                    {
                        timestamp: '2021-01-01T00:00:00.000Z',
                        properties: {
                            hobby: 'coding',
                            name: 'Derry',
                        },
                        relevant_event_count: 997,
                    },
                ],
                crucial_property_keys: [], // No key properties here
                effective_date_from: '2021-01-01T00:00:00.000000+00:00',
                effective_date_to: '2021-06-01T23:59:59.999999+00:00',
            } as PropertiesTimelineResponseApi,
        },
    })

    return (
        <div className="border rounded w-120">
            <PropertiesTimeline actor={examplePerson} query={EXAMPLE_QUERY} />
        </div>
    )
}
