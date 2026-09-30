import { TodaySessionIconKind, todaySessionIcon } from './todaySessionIcon'
import { TodayWorkItem } from './todayWorkItems'

const item = (kind: TodayWorkItem['kind'], status: string | null): TodayWorkItem => ({
    kind,
    id: 'id',
    title: 'Title',
    timestamp: null,
    status,
    channel: null,
})

describe('todaySessionIcon', () => {
    it.each<[string, TodayWorkItem, boolean, TodaySessionIconKind]>([
        ['a chat', item('chat', null), false, 'chat'],
        ['a running session, even when pinned', item('session', 'in_progress'), true, 'running'],
        ['a finished session, even when pinned', item('session', 'completed'), true, 'completed'],
        ['a failed session', item('session', 'failed'), false, 'failed'],
        ['a cancelled session', item('session', 'cancelled'), false, 'stopped'],
        ['a pinned session with no run', item('session', null), true, 'pinned'],
        ['a queued session', item('session', 'queued'), false, 'queued'],
        ['a session with no run', item('session', null), false, 'session'],
    ])('shows %s as %s', (_, workItem, pinned, expected) => {
        expect(todaySessionIcon(workItem, pinned)).toBe(expected)
    })
})
