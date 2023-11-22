import { Meta, Story } from '@storybook/react'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { RawPropertiesTimelineResult } from 'lib/components/PropertiesTimeline/propertiesTimelineLogic'

import { useStorybookMocks } from '~/mocks/browser'

import EXAMPLE_PERSONS_RESPONSE from './__mocks__/examplePersonsResponse.json'
import { PersonsModal as PersonsModalComponent } from './PersonsModal'

const meta: Meta = {
    title: 'Scenes-App/Persons Modal',
    component: PersonsModalComponent,
}
export default meta
export const PersonsModal: Story = () => {
    useStorybookMocks({
        get: {
            [EXAMPLE_PERSONS_RESPONSE.initial]: EXAMPLE_PERSONS_RESPONSE,
            [`/api/projects/${MOCK_TEAM_ID}/persons/${EXAMPLE_PERSONS_RESPONSE.results[0].people[0].uuid}/properties_timeline/`]:
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
