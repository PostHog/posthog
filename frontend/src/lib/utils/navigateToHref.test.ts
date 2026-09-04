import { router } from 'kea-router'

import { navigateToHref } from 'lib/utils/navigateToHref'

import { AppContext } from '~/types'

jest.mock('kea-router', () => ({
    router: { actions: { push: jest.fn() } },
}))

const push = router.actions.push as jest.Mock

describe('navigateToHref', () => {
    const originalLocation = window.location
    const originalAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        push.mockReset()
        Object.defineProperty(window, 'location', {
            value: { ...window.location, href: 'https://us.posthog.com/project/997/dashboard' },
            configurable: true,
        })
        window.POSTHOG_APP_CONTEXT = { current_team: { id: 997 } } as unknown as AppContext
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
        window.POSTHOG_APP_CONTEXT = originalAppContext
    })

    it('routes an in-app path client-side', () => {
        navigateToHref('/insights/abc123')

        expect(push).toHaveBeenCalledWith('/insights/abc123')
        expect(window.location.href).toEqual('https://us.posthog.com/project/997/dashboard')
    })

    it.each([undefined, '', '#'])('navigates nowhere for %p', (href) => {
        navigateToHref(href)

        expect(push).not.toHaveBeenCalled()
        expect(window.location.href).toEqual('https://us.posthog.com/project/997/dashboard')
    })

    it.each(['https://posthog.com/docs', 'mailto:hey@posthog.com', '/api/projects/997/exports/1'])(
        'loads %p as a page instead of routing it',
        (href) => {
            navigateToHref(href)

            expect(push).not.toHaveBeenCalled()
            expect(window.location.href).toEqual(href)
        }
    )

    it('falls back to a project-scoped page load when the History API rejects the push', () => {
        push.mockImplementation(() => {
            throw new DOMException('The operation is insecure.', 'SecurityError')
        })

        navigateToHref('/insights/abc123')

        expect(window.location.href).toEqual('/project/997/insights/abc123')
    })

    it('lets an error from a logic reacting to the navigation through', () => {
        push.mockImplementation(() => {
            throw new Error('a scene logic blew up')
        })

        expect(() => navigateToHref('/insights/abc123')).toThrow('a scene logic blew up')
        expect(window.location.href).toEqual('https://us.posthog.com/project/997/dashboard')
    })
})
