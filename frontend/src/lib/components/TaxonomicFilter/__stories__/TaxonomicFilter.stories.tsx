import React from 'react'
import { TaxonomicFilter } from '../TaxonomicFilter'
import { Provider } from 'kea'
import { taxonomicFilterLogic } from '../taxonomicFilterLogic'
import { createMemoryHistory } from 'history'
import { initKea } from '~/initKea'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { worker } from '~/mocks/browser'
import { DefaultRequestBody, rest } from 'msw'
import { CohortType, PersonProperty, PropertyDefinition } from '~/types'

export default {
    title: 'PostHog/Components/TaxonomicFilter',
}

export const AllGroups = (): JSX.Element => {
    // This is lifted from keaStory. I wanted to see what was the minimum we
    // needed to get setup, without needing to inject a `state` snapshot.
    const history = createMemoryHistory()
    ;(history as any).pushState = history.push
    ;(history as any).replaceState = history.replace
    initKea({ routerLocation: history.location, routerHistory: history })

    personPropertiesModel.mount()
    cohortsModel.mount()
    taxonomicFilterLogic.mount()

    // TODO: Add propery typing to API responses/requests in application code.
    // This is to ensure that if the typing changes there, that we will be
    // informed that we need to update this data as well. We should be
    // maintaining some level of backwards compatability so hopefully this isn't
    // too unnecessarily laborious
    // TODO: abstract away the api details behind, e.g.
    // `setupPersonPropertiesEndpoint(rest...)`. This was we can keep the urls and
    // typings in one place, but still give the freedom to do whatever we want
    // in the rest handlers
    worker.use(
        rest.get<DefaultRequestBody, Array<PersonProperty>>('/api/person/properties', (_, res, ctx) => {
            return res(
                ctx.json([
                    { id: 1, name: 'location', count: 1 },
                    { id: 2, name: 'role', count: 2 },
                    { id: 3, name: 'height', count: 3 },
                ])
            )
        }),
        rest.get<DefaultRequestBody, PropertyDefinition[]>(
            '/api/projects/@current/property_definitions',
            (_, res, ctx) => {
                return res(
                    ctx.json([
                        {
                            id: 'a',
                            name: 'signed up',
                            description: 'signed up',
                            volume_30_day: 10,
                            query_usage_30_day: 5,
                            count: 101,
                        },
                        {
                            id: 'b',
                            name: 'viewed insights',
                            description: 'signed up',
                            volume_30_day: 10,
                            query_usage_30_day: 5,
                            count: 1,
                        },
                        {
                            id: 'c',
                            name: 'logged out',
                            description: 'signed up',
                            volume_30_day: 10,
                            query_usage_30_day: 5,
                            count: 103,
                        },
                    ])
                )
            }
        ),
        rest.get<DefaultRequestBody, { results: CohortType[] }>('/api/cohort/', (_, res, ctx) => {
            return res(
                ctx.json({
                    results: [
                        {
                            id: 1,
                            name: 'Properties Cohort',
                            count: 1,
                            groups: [{ id: 'a', name: 'Properties Group', count: 1, matchType: 'properties' }],
                        },
                        {
                            id: 2,
                            name: 'Entities Cohort',
                            count: 1,
                            groups: [{ id: 'b', name: 'Entities Group', count: 1, matchType: 'entities' }],
                        },
                    ],
                })
            )
        })
    )

    return (
        <Provider>
            <TaxonomicFilter />
        </Provider>
    )
}
