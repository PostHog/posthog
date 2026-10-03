import * as kea from 'kea'
import * as React from 'react'

import { CodeTaskLink, taskDeepLink } from './CodeTaskLink'

jest.mock('react', () => ({
    ...jest.requireActual('react'),
    useEffect: jest.fn(),
}))

describe('CodeTaskLink', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    it('forwards the comment target from the browser URL to PostHog Desktop', () => {
        expect(
            taskDeepLink('task/1', {
                comment: 'comment/1',
                scope: 'task_artifact',
                item: 'artifact/1',
            })
        ).toBe('posthog-code://task/task%2F1?comment=comment%2F1&scope=task_artifact&item=artifact%2F1')
    })

    it('reads the comment target from the active URL when rendering the bridge', () => {
        jest.spyOn(kea, 'useValues').mockReturnValue({
            searchParams: { comment: 'comment-1' },
        } as never)

        CodeTaskLink({ taskId: 'task-1' })

        expect(React.useEffect).toHaveBeenCalledWith(expect.any(Function), [
            'posthog-code://task/task-1?comment=comment-1',
        ])
    })
})
