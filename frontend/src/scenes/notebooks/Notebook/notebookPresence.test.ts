import {
    getNotebookMarkdownClientId,
    getNotebookPresenceParticipants,
    getNotebookRemoteParticipants,
    pruneNotebookRemotePresence,
} from './notebookPresence'

describe('notebookPresence', () => {
    let originalGetEntriesByType: Performance['getEntriesByType'] | undefined

    beforeEach(() => {
        originalGetEntriesByType = window.performance.getEntriesByType
        sessionStorage.clear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        if (originalGetEntriesByType) {
            Object.defineProperty(window.performance, 'getEntriesByType', {
                configurable: true,
                value: originalGetEntriesByType,
            })
        } else {
            Reflect.deleteProperty(window.performance, 'getEntriesByType')
        }
        sessionStorage.clear()
    })

    function mockNavigationType(type: PerformanceNavigationTiming['type']): void {
        const entries = [{ type } as PerformanceNavigationTiming]
        const getEntriesByType = window.performance.getEntriesByType
        if (jest.isMockFunction(getEntriesByType)) {
            getEntriesByType.mockReturnValue(entries)
            return
        }
        Object.defineProperty(window.performance, 'getEntriesByType', {
            configurable: true,
            value: jest.fn().mockReturnValue(entries),
        })
    }

    it('shows people instead of client tabs by keeping the latest presence for each user', () => {
        const participants = getNotebookRemoteParticipants({
            oldTab: {
                clientId: 'oldTab',
                userId: 1,
                userName: 'Zoe',
                lastSeenAt: 10,
            },
            bob: {
                clientId: 'bob',
                userId: 2,
                userName: 'Bob',
                lastSeenAt: 30,
            },
            newTab: {
                clientId: 'newTab',
                userId: 1,
                userName: 'Zoe',
                lastSeenAt: 20,
            },
        })

        expect(participants).toEqual([
            {
                clientId: 'bob',
                userId: 2,
                userName: 'Bob',
                lastSeenAt: 30,
            },
            {
                clientId: 'newTab',
                userId: 1,
                userName: 'Zoe',
                lastSeenAt: 20,
            },
        ])
    })

    it('prunes stale presence and preserves state identity when nothing expires', () => {
        const state = {
            stale: {
                clientId: 'stale',
                userId: 1,
                userName: 'Stale user',
                lastSeenAt: 60,
            },
            fresh: {
                clientId: 'fresh',
                userId: 2,
                userName: 'Fresh user',
                lastSeenAt: 90,
            },
        }

        expect(pruneNotebookRemotePresence(state, 100, 40)).toBe(state)
        expect(pruneNotebookRemotePresence(state, 100, 29)).toEqual({
            fresh: {
                clientId: 'fresh',
                userId: 2,
                userName: 'Fresh user',
                lastSeenAt: 90,
            },
        })
    })

    it('prepends the current user and removes remote echoes of the same user', () => {
        expect(
            getNotebookPresenceParticipants(
                {
                    id: 1,
                    first_name: 'Current User',
                    email: 'current@example.com',
                },
                [
                    {
                        clientId: 'sameUserOtherTab',
                        userId: 1,
                        userName: 'Current User',
                        lastSeenAt: 20,
                    },
                    {
                        clientId: 'otherUser',
                        userId: 2,
                        userName: 'Other User',
                        lastSeenAt: 30,
                    },
                ],
                40
            )
        ).toEqual([
            {
                clientId: 'current-user',
                userId: 1,
                userName: 'You',
                lastSeenAt: 40,
                isCurrentUser: true,
                profileUser: {
                    id: 1,
                    first_name: 'Current User',
                    email: 'current@example.com',
                },
            },
            {
                clientId: 'otherUser',
                userId: 2,
                userName: 'Other User',
                lastSeenAt: 30,
            },
        ])
    })

    it('reuses the markdown client id after a browser reload', () => {
        mockNavigationType('navigate')
        const clientId = getNotebookMarkdownClientId()

        mockNavigationType('reload')

        expect(getNotebookMarkdownClientId()).toEqual(clientId)
    })

    it('creates a new markdown client id for a separate tab navigation', () => {
        mockNavigationType('navigate')
        const firstTabClientId = getNotebookMarkdownClientId()

        mockNavigationType('navigate')

        expect(getNotebookMarkdownClientId()).not.toEqual(firstTabClientId)
    })
})
