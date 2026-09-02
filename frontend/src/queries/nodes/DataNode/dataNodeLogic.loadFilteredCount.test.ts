import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import * as queryModule from '~/queries/query'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const testUniqueKey = 'testFilteredCountKey'

describe('dataNodeLogic - loadFilteredCount', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // Regression test: a second loadFilteredCount call supersedes the first via kea's
    // breakpoint mechanism, which throws 'kea-listeners breakpoint broke'. Without an
    // isBreakpoint guard, the superseded call's catch block reported it as a real error
    // and returned null, letting a stale or blank count land on the table.
    it('does not report a superseded loadFilteredCount call as an error', async () => {
        const query: ActorsQuery = {
            kind: NodeKind.ActorsQuery,
            select: ['id'],
            search: 'first search',
        }
        logic = dataNodeLogic({ key: testUniqueKey, query })
        logic.mount()

        let resolveFirstQuery: (value: any) => void = () => {}
        const firstQuery = new Promise((resolve) => {
            resolveFirstQuery = resolve
        })
        const performQuerySpy = jest
            .spyOn(queryModule, 'performQuery')
            .mockReturnValueOnce(firstQuery as any)
            .mockResolvedValueOnce({ results: [[5]] } as any)

        // Dispatch the first call and let its debounce clear, so it's awaiting performQuery
        // (the slow, unresolved firstQuery) when the second call comes in.
        logic.actions.loadFilteredCount()
        await new Promise((resolve) => setTimeout(resolve, 350))
        expect(performQuerySpy).toHaveBeenCalledTimes(1)

        // The second call supersedes the first via kea's breakpoint mechanism.
        logic.actions.loadFilteredCount()
        await expectLogic(logic).toDispatchActions(['loadFilteredCountSuccess'])
        expect(logic.values.filteredCount).toBe(5)

        // Now let the superseded first call's query resolve — its breakpoint() should throw
        // and be swallowed as a cancellation, not treated as a real error.
        resolveFirstQuery({ results: [[1]] })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(posthog.captureException).not.toHaveBeenCalled()
        expect(logic.values.filteredCount).toBe(5)
    })
})
