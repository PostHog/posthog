import { osSidePanelPath } from './osSidePanelPath'

describe('osSidePanelPath', () => {
    test.each([
        ['PostHog AI with an auto-run prompt', 'max', '!why did signups drop', '/ai?ask=why%20did%20signups%20drop'],
        ['PostHog AI without a prompt', 'max', undefined, '/ai'],
        ['PostHog AI with a prompt that only seeds the composer', 'max', 'draft', '/ai'],
        ['activity', 'activity', undefined, '/activity-logs'],
        ['a notebook', 'notebook', 'abc123', '/notebooks/abc123'],
        ['a notebook id that is a path', 'notebook', '../../settings', '/notebooks'],
        ['exports', 'exports', undefined, '/exports'],
        ['support, which the window opens itself', 'support', 'bug:analytics', null],
        ['discussions, which have no page', 'discussion', undefined, null],
    ])('%s', (_description, tab, options, expected) => {
        expect(osSidePanelPath(tab, options)).toBe(expected)
    })
})
