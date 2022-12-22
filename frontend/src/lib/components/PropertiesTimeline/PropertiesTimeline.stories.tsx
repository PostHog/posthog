import { ComponentMeta } from '@storybook/react'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { useStorybookMocks } from '~/mocks/browser'
import { PersonActorType } from '~/types'
import { PropertiesTimeline } from '.'
import { RawPropertiesTimelineResult } from './propertiesTimelineLogic'

export default {
    title: 'Components/Properties Timeline',
    component: PropertiesTimeline,
} as ComponentMeta<typeof PropertiesTimeline>

const EXAMPLE_PERSON: PersonActorType = {
    type: 'person',
    id: 1,
    uuid: '012e89b5-4239-4319-8ae4-d3cae2f5deb3',
    distinct_ids: ['one'],
    is_identified: true,
    properties: {},
    created_at: '2021-01-01T00:00:00.000Z',
    matched_recordings: [],
    value_at_data_point: null,
}

export function MultiplePointsForPerson(): JSX.Element {
    useStorybookMocks({
        get: {
            [`/api/projects/${MOCK_TEAM_ID}/persons/${EXAMPLE_PERSON.uuid}/properties_timeline/`]: {
                points: [
                    {
                        timestamp: '2021-01-01T00:00:00.000Z',
                        properties: {
                            hobby: 'hiking',
                            name: 'Perry',
                        },
                        relevantEventCount: 3,
                    },
                    {
                        timestamp: '2021-01-17T00:00:00.000Z',
                        properties: {
                            hobby: 'hiking',
                            name: 'Jerry',
                        },
                        relevantEventCount: 3,
                    },
                    {
                        timestamp: '2021-01-18T08:00:00.000Z',
                        properties: {
                            hobby: 'sailing',
                            name: 'Kerry',
                        },
                        relevantEventCount: 3,
                    },
                    {
                        timestamp: '2021-03-01T00:00:00.000Z',
                        properties: {
                            hobby: 'hiking',
                            name: 'Terry',
                        },
                        relevantEventCount: 1,
                    },
                ],
                crucial_property_keys: ['name'],
            } as RawPropertiesTimelineResult,
        },
    })

    return (
        <div className="border rounded max-w-120">
            <PropertiesTimeline actor={EXAMPLE_PERSON} filter={{}} />
        </div>
    )
}
