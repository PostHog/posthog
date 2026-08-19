import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import * as queryModule from '~/queries/query'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const testUniqueKey = 'testCountErrorsKey'

describe('dataNodeLogic - count query errors', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    const query: ActorsQuery = {
        kind: NodeKind.ActorsQuery,
        select: ['id'],
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // The count query for an ActorsQuery is a HogQLQuery, so failing only HogQLQuery lets the main
    // data load succeed and keeps the global loaders `onFailure` handler out of these assertions.
    const failCountWith = (error: ApiError): void => {
        jest.spyOn(queryModule, 'performQuery').mockImplementation(async (q: any) => {
            if (q?.kind === NodeKind.HogQLQuery) {
                throw error
            }
            return { results: [] } as any
        })
    }

    it('does not re-capture a plain server 5xx that the server already reports', async () => {
        failCountWith(new ApiError('A server error occurred.', 500))
        logic = dataNodeLogic({ key: testUniqueKey, query })
        logic.mount()

        logic.actions.loadTotalCount()
        await expectLogic(logic).toDispatchActions(['loadTotalCountSuccess'])

        expect(posthog.captureException).not.toHaveBeenCalled()
        // The count is unavailable, but the failure flag lets the table show a retry hint
        // instead of letting the count vanish silently.
        expect(logic.values.totalCount).toBeNull()
        expect(logic.values.totalCountLoadFailed).toBe(true)
    })

    it('captures a non-5xx failure with the query kind and response status', async () => {
        failCountWith(new ApiError('Bad request', 400))
        logic = dataNodeLogic({ key: testUniqueKey, query })
        logic.mount()

        logic.actions.loadTotalCount()
        await expectLogic(logic).toDispatchActions(['loadTotalCountSuccess'])

        expect(posthog.captureException).toHaveBeenCalledWith(
            expect.any(ApiError),
            expect.objectContaining({
                // The fingerprint is what splits these off the shared-stack bucket; the plain
                // properties alone do not change grouping.
                $exception_fingerprint: 'load total count in dataNodeLogic (kind=HogQLQuery, status=400)',
                action: 'load total count in dataNodeLogic',
                query_kind: NodeKind.HogQLQuery,
                response_status: 400,
            })
        )
        expect(logic.values.totalCountLoadFailed).toBe(true)
    })
})
