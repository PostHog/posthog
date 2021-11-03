import { Meta } from '@storybook/react'
import { Provider } from 'kea'
import React from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { initKea } from '~/initKea'
import { worker } from '~/mocks/browser'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { mockGetPersonProperties } from '../TaxonomicFilter/__stories__/TaxonomicFilter.stories'
import { PersonPropertySelect } from './PersonPropertySelect'

export default {
    title: 'Components/PersonPropertySelect',
} as Meta

export const Default = (): JSX.Element => {
    const [selectedProperties, setSelectProperties] = React.useState<string[]>([])

    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.delay(1500),
                ctx.json([
                    { name: 'Property A', count: 10 },
                    { name: 'Property B', count: 20 },
                    { name: 'Property C', count: 30 },

                    { name: 'Property D', count: 40 },
                    { name: 'Property E', count: 50 },
                    { name: 'Property F', count: 60 },

                    { name: 'Property G', count: 70 },
                    { name: 'Property H', count: 80 },
                    { name: 'Property I', count: 90 },
                ])
            )
        )
    )

    initKea()
    personPropertiesModel.mount()

    // Need to mount teamLogic otherwise we get erros regarding not being able
    // to find the storre for team. It also makes some API calls to
    // `/api/projects/@current` and `/api/organizations/@current` although I
    // haven't mocked these as the component still works without doing so
    teamLogic.mount()

    return (
        <Provider>
            <PersonPropertySelect selectedProperties={selectedProperties} onChange={setSelectProperties} />
        </Provider>
    )
}
