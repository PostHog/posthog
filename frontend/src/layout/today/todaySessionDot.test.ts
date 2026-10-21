import { TodaySessionDot, todaySessionDot } from './todaySessionDot'

describe('todaySessionDot', () => {
    it.each<
        [string, string | null, string | null, boolean, Omit<TodaySessionDot, 'faint'> & { faint?: boolean }, string?]
    >([
        ['a failed run, even when unread', 'failed', 'cloud', true, { mark: 'failed', label: 'Failed' }],
        ['a queued cloud run', 'queued', 'cloud', false, { mark: 'spinner', label: 'Queued' }],
        ['a cloud run that has not started', 'not_started', 'cloud', true, { mark: 'spinner', label: 'Starting' }],
        ['a queued local run', 'queued', 'local', false, { mark: 'hollow', label: 'Queued' }],
        ['a running session, even when unread', 'in_progress', 'cloud', true, { mark: 'spinner', label: 'Working' }],
        [
            'an interactive session between turns',
            'in_progress',
            'cloud',
            false,
            { mark: 'hollow', label: 'Idle' },
            'interactive',
        ],
        ['an unread finished session', 'completed', 'cloud', true, { mark: 'solid', label: 'Unread' }],
        ['a finished session', 'completed', 'cloud', false, { mark: 'hollow', label: 'Completed' }],
        ['a stopped session', 'cancelled', 'cloud', false, { mark: 'hollow', faint: true, label: 'Stopped' }],
        ['a session with no run', null, null, false, { mark: 'hollow', label: 'Idle' }],
    ])('shows %s', (_, status, runEnvironment, unread, expected, runMode = 'background') => {
        expect(todaySessionDot({ status, runEnvironment, runMode }, unread)).toEqual({ faint: false, ...expected })
    })
})
