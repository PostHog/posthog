import { CohortType, PersonProperty, PropertyDefinition } from '~/types'
import { ResponseResolver, rest, RestContext, RestRequest } from 'msw'
import { worker } from '~/mocks/browser'

export type GetPersonPropertiesResponse = PersonProperty[]
export type GetPersonPropertiesRequest = undefined

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types, @typescript-eslint/explicit-function-return-type
export const mockGetPersonProperties = (
    handler: ResponseResolver<RestRequest<GetPersonPropertiesRequest, any>, RestContext, GetPersonPropertiesResponse>
) => rest.get<GetPersonPropertiesRequest, GetPersonPropertiesResponse>('/api/person/properties', handler)

type GetPropertyDefinitionsResponse = PropertyDefinition[]
type GetPropertyDefinitionsRequest = undefined

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types, @typescript-eslint/explicit-function-return-type
export const mockGetPropertyDefinitions = (
    handler: ResponseResolver<
        RestRequest<GetPropertyDefinitionsRequest, any>,
        RestContext,
        GetPropertyDefinitionsResponse
    >
) =>
    rest.get<GetPropertyDefinitionsRequest, GetPropertyDefinitionsResponse>(
        '/api/projects/@current/property_definitions',
        handler
    )

type GetCohortsResponse = { results: CohortType[] }
type GetCohortsRequest = undefined

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types, @typescript-eslint/explicit-function-return-type
export const mockGetCohorts = (
    handler: ResponseResolver<RestRequest<GetCohortsRequest, any>, RestContext, GetCohortsResponse>
) => rest.get<GetCohortsRequest, GetCohortsResponse>('/api/projects/1/cohorts/', handler)

export function defaultFilterMocks(): void {
    // TODO: Add propery typing to API responses/requests in application code.
    // This is to ensure that if the typing changes there, that we will be
    // informed that we need to update this data as well. We should be
    // maintaining some level of backwards compatability so hopefully this isn't
    // too unnecessarily laborious
    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: 'location', count: 1 },
                    { id: 2, name: 'role', count: 2 },
                    { id: 3, name: 'height', count: 3 },
                    { id: 4, name: '$browser', count: 4 },
                ])
            )
        ),
        mockGetPropertyDefinitions((_, res, ctx) =>
            res(
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
        ),
        mockGetCohorts((_, res, ctx) =>
            res(
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
        )
    )
}
