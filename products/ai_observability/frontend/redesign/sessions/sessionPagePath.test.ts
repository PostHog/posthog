import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { sessionPageIdFromPath } from './sessionPagePath'

describe('sessionPageIdFromPath', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([['session-1'], ['session:group:16-16:81008d53ff0a708b'], ['a/b%c ü'], ['x?y#z&w=1+2'], ['%2F literally']])(
        'session id %s round-trips through the page url',
        (sessionId) => {
            router.actions.push(urls.aiObservabilitySession(sessionId, { timestamp: '2026-09-01T10:15:00Z' }))
            expect(sessionPageIdFromPath(router.values.location.pathname)).toEqual(sessionId)
        }
    )

    it.each([
        ['session:group:16', '/ai-observability/sessions/session:group:16'],
        ['chat 42', '/ai-observability/sessions/chat%2042'],
    ])('keeps the characters of the id %s that the route accepts as they are', (sessionId, path) => {
        expect(urls.aiObservabilitySession(sessionId)).toEqual(path)
    })

    it.each([[urls.aiObservabilitySessions()], [urls.aiObservabilityTraces()], ['/ai-observability/sessions/a/b']])(
        'reads no session from %s',
        (pathname) => {
            expect(sessionPageIdFromPath(pathname)).toBeNull()
        }
    )
})
