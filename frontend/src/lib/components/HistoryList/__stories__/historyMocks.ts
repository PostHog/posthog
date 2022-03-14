import { ResponseResolver, rest, RestContext, RestRequest } from 'msw'
import { worker } from '~/mocks/browser'
import { PaginatedResponse } from 'lib/api'
import { HistoryActions, HistoryListItem } from 'lib/components/HistoryList/historyListLogic'

export type Res = PaginatedResponse<HistoryListItem>
export type Req = undefined

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types, @typescript-eslint/explicit-function-return-type
export const mockGetFeatureFlagHistory = (handler: ResponseResolver<RestRequest<Req, any>, RestContext, Res>) =>
    rest.get<Req, Res>(`/api/projects/@current/feature_flags/7/history`, handler)

export function defaultHistoryMocks(): void {
    // TODO: Add proper typing to API responses/requests in application code.
    // This is to ensure that if the typing changes there, that we will be
    // informed that we need to update this data as well. We should be
    // maintaining some level of backwards compatability so hopefully this isn't
    // too unnecessarily laborious
    worker.use(
        mockGetFeatureFlagHistory((_, res, ctx) =>
            res(
                ctx.json({
                    results: featureFlagsHistoryResponseJson,
                })
            )
        )
    )
}

export function emptyHistoryMocks(): void {
    // TODO: Add proper typing to API responses/requests in application code.
    // This is to ensure that if the typing changes there, that we will be
    // informed that we need to update this data as well. We should be
    // maintaining some level of backwards compatability so hopefully this isn't
    // too unnecessarily laborious
    worker.use(
        mockGetFeatureFlagHistory((_, res, ctx) =>
            res(
                ctx.json({
                    results: [],
                })
            )
        )
    )
}

const featureFlagsHistoryResponseJson = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        action: HistoryActions.FEATURE_FLAG_CREATED,
        detail: {
            id: 7,
            name: 'test flag',
        },
        created_at: '2022-02-05T16:28:39.594Z',
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        action: HistoryActions.FEATURE_FLAG_DESCRIPTION_CHANGED,
        detail: {
            id: 7,
            to: 'this is what was added',
        },
        created_at: '2022-02-06T16:28:39.594Z',
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        action: HistoryActions.FEATURE_FLAG_FILTERS_CHANGED,
        detail: {
            id: 7,
            to: "{ 'filter': 'info' }",
        },
        created_at: '2022-02-08T16:28:39.594Z',
    },
    {
        email: 'paul@posthog.com',
        name: 'paul',
        action: HistoryActions.FEATURE_FLAG_ACTIVE_CHANGED,
        detail: {
            id: 7,
            to: false,
        },
        created_at: '2022-02-08T16:45:39.594Z',
    },
]
