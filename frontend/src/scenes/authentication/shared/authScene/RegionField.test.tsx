import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RegionField } from './RegionField'

describe('RegionField', () => {
    const originalLocation = window.location

    beforeEach(() => {
        useMocks({
            get: {
                '/_preflight/': () => [200, { ...preflightJson, cloud: true, region: 'US', realm: 'cloud' }],
            },
        })
        initKeaTests()
        router.actions.push('/signup')
        // The cross-region hop assigns window.location.href; stub it so jsdom does not attempt to
        // navigate and the switching state can be asserted.
        Object.defineProperty(window, 'location', {
            value: { ...originalLocation, href: '' },
            configurable: true,
            writable: true,
        })
        render(
            <Provider>
                <RegionField />
            </Provider>
        )
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true, writable: true })
        cleanup()
    })

    it('shows a switching state and hands off to the other cloud host when the region changes', async () => {
        const trigger = await screen.findByText('United States')
        await userEvent.click(trigger)
        await userEvent.click(await screen.findByText('European Union'))

        expect(await screen.findByText('Switching to European Union…')).toBeVisible()
        expect(window.location.href).toBe('https://eu.posthog.com/signup')
    })
})
