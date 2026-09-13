import { taskDeepLink } from './CodeTaskLink'

describe('CodeTaskLink', () => {
    it.each([
        [
            'forwards the comment target from the browser URL to PostHog Desktop',
            { comment: 'comment/1', scope: 'task_artifact', item: 'artifact/1' },
            'posthog-code://task/task%2F1?comment=comment%2F1&scope=task_artifact&item=artifact%2F1',
        ],
        ['drops params PostHog Desktop does not read', { other: 'ignored' }, 'posthog-code://task/task%2F1'],
    ])('%s', (_name, searchParams, expected) => {
        expect(taskDeepLink('task/1', searchParams)).toBe(expected)
    })
})
