import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { webVitalsToolbarLogic } from './webVitalsToolbarLogic'

jest.mock('~/toolbar/toolbarFetch', () => ({
    toolbarFetch: jest.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
}))

jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

describe('webVitalsToolbarLogic', () => {
    let logic: ReturnType<typeof webVitalsToolbarLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic
            .build({
                posthog: {
                    config: { ui_host: 'https://us.posthog.com/' },
                    webVitalsAutocapture: { isEnabled: true },
                } as any,
            } as any)
            .mount()
        logic = webVitalsToolbarLogic.build()
        logic.mount()
    })

    it('degrades to null metrics without reporting a network failure as an exception', async () => {
        await expectLogic(logic, () => {
            logic.actions.getWebVitals()
        })
            .toFinishAllListeners()
            .toMatchValues({
                remoteWebVitals: { LCP: null, FCP: null, CLS: null, INP: null },
            })

        // A benign fetch rejection on a customer page must not pollute error tracking.
        expect(captureToolbarException).not.toHaveBeenCalled()
    })
})
