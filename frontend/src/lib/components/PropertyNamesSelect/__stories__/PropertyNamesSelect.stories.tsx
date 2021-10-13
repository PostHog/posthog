import { mockGetPersonProperties } from 'lib/components/TaxonomicFilter/__stories__/TaxonomicFilter.stories'
import React from 'react'
import { worker } from '~/mocks/browser'
import { PropertyNamesSelect } from '../PropertyNamesSelect'

export default {
    title: 'PostHog/Components/PropertyNamesSelect',
}

export const EmptyWithOptions = (): JSX.Element => {
    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: 'location', count: 10 },
                    { id: 1, name: 'age', count: 10 },
                ])
            )
        )
    )

    return <PropertyNamesSelect />
}
