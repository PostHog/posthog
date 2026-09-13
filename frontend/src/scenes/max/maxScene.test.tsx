import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { Max, scene } from './Max'

// The heavy runner is irrelevant here; record what the scene hands it.
const renderedTaskIds: (string | undefined)[] = []
jest.mock('./components/AiFirstMaxInstance', () => ({
    AiFirstMaxInstance: ({ taskId }: { taskId?: string }) => {
        renderedTaskIds.push(taskId)
        return null
    },
}))

describe('Max scene parameters', () => {
    const validTaskId = '0199ed4a-5c03-0000-3220-df21df612e95'

    beforeEach(() => {
        renderedTaskIds.length = 0
        initKeaTests()
    })

    afterEach(cleanup)

    it('accepts a UUID task ID', () => {
        expect(scene.paramsToProps?.({ params: {}, searchParams: { task: validTaskId }, hashParams: {} })).toEqual({
            taskId: validTaskId,
        })
    })

    it.each(['.', '..', '../../99', 'task-1'])('rejects invalid task ID %s', (taskId) => {
        expect(scene.paramsToProps?.({ params: {}, searchParams: { task: taskId }, hashParams: {} })).toEqual({
            taskId: undefined,
        })
    })

    // Regression coverage: `paramsToProps` feeds the scene logic, and the app spreads only the
    // route's path params into the component. `/ai` declares none, so a component that trusted a
    // `taskId` prop saw `undefined` on every task link and opened the composer instead. Asserting
    // `paramsToProps` in isolation cannot catch that, because it stays correct while unused.
    it.each([
        ['selects the task named by the URL', urls.aiTask(validTaskId), validTaskId],
        ['selects no task for a non-UUID task param', '/ai?task=task-1', undefined],
        ['selects no task when the URL names none', urls.ai(), undefined],
    ])('%s', (_name, url, expected) => {
        router.actions.push(url)

        render(<Max />)

        expect(renderedTaskIds).toEqual([expected])
    })
})
