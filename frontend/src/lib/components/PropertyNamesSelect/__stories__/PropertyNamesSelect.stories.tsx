import { Provider } from 'kea'
import { mockGetPersonProperties } from 'lib/components/TaxonomicFilter/__stories__/TaxonomicFilter.stories'
import React from 'react'
import { initKea } from '~/initKea'
import { worker } from '~/mocks/browser'
import { PropertyNamesSelect } from '../PropertyNamesSelect'

export default {
    title: 'PostHog/Components/PropertyNamesSelect',
}

export const EmptyWithOptions = (): JSX.Element => {
    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.delay(1500),
                ctx.json([
                    { id: 1, name: 'Property A', count: 10 },
                    { id: 2, name: 'Property B', count: 20 },
                    { id: 3, name: 'Property C', count: 30 },

                    { id: 4, name: 'Property D', count: 40 },
                    { id: 5, name: 'Property E', count: 50 },
                    { id: 6, name: 'Property F', count: 60 },

                    { id: 7, name: 'Property G', count: 70 },
                    { id: 8, name: 'Property H', count: 80 },
                    { id: 9, name: 'Property I', count: 90 },
                ])
            )
        )
    )

    initKea()

    return (
        <Provider>
            <PropertyNamesSelect
                onChange={(selectedProperties) => console.log('Selected Properties', selectedProperties)}
            />
        </Provider>
    )
}
