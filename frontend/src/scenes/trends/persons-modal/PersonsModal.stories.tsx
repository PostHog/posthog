import { Meta, Story } from '@storybook/react'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { RawPropertiesTimelineResult } from 'lib/components/PropertiesTimeline/propertiesTimelineLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { PersonsModal as PersonsModalComponent } from './PersonsModal'
import EXAMPLE_PERSONS_RESPONSE from './__mocks__/examplePersonsResponse.json'

export default {
    title: 'Scenes-App/Persons Modal',
    component: PersonsModalComponent,
} as Meta

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
                            relevantEventCount: 2,
                        },
                        {
                            timestamp: '2022-12-02T08:00:00.000Z',
                            properties: {
                                name: 'Francisco Elliott',
                                email: 'mortgage2056@yandex.com',
                                $geoip_country_code: 'PL',
                            },
                            relevantEventCount: 9,
                        },
                        {
                            timestamp: '2022-12-08T00:00:00.000Z',
                            properties: {
                                name: 'Francisco Elliott',
                                email: 'mortgage2056@yandex.com',
                                $geoip_country_code: 'DE',
                            },
                            relevantEventCount: 155,
                        },
                        {
                            timestamp: '2022-12-12T00:00:00.000Z',
                            properties: {
                                name: 'Francisco Elliott',
                                email: 'mortgage2056@yandex.com',
                                $geoip_country_code: 'CN',
                            },
                            relevantEventCount: 13,
                        },
                    ],
                    crucial_property_keys: ['$geoip_country_code'],
                } as RawPropertiesTimelineResult,
        },
    })
    useFeatureFlags([FEATURE_FLAGS.ACTOR_PROPERTIES_TIMELINE])

    return (
        <div className="flex max-h-200">
            <PersonsModalComponent title="Hello!" url={EXAMPLE_PERSONS_RESPONSE.initial} inline />
        </div>
    )
}
