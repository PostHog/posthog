import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { webVitalsToolbarLogic } from './webVitalsToolbarLogic'

describe('webVitalsToolbarLogic', () => {
    let webVitalsGet: jest.SpyInstance

    const mountConfig = (accessToken: string | null): void => {
        toolbarConfigLogic
            .build({
                posthog: {
                    config: { ui_host: 'https://us.posthog.com/' },
                    webVitalsAutocapture: { isEnabled: true },
                    on: jest.fn(),
                } as any,
                accessToken: accessToken ?? undefined,
            } as any)
            .mount()
    }

    beforeEach(() => {
        initKeaTests()
        webVitalsGet = jest
            .spyOn(toolbarApi.webVitals, 'get')
            .mockResolvedValue({ ok: true, data: { results: [] } } as any)
    })

    afterEach(() => {
        webVitalsGet.mockRestore()
    })

    it('does not request web vitals while unauthenticated', async () => {
        mountConfig(null)
        webVitalsToolbarLogic.mount()

        await expectLogic(webVitalsToolbarLogic).toFinishAllListeners()

        expect(webVitalsGet).not.toHaveBeenCalled()
    })

    it('requests web vitals once authenticated', async () => {
        mountConfig('an-access-token')
        webVitalsToolbarLogic.mount()

        await expectLogic(webVitalsToolbarLogic).toFinishAllListeners()

        expect(webVitalsGet).toHaveBeenCalled()
    })

    it('requests web vitals after authentication completes', async () => {
        mountConfig(null)
        webVitalsToolbarLogic.mount()
        await expectLogic(webVitalsToolbarLogic).toFinishAllListeners()
        expect(webVitalsGet).not.toHaveBeenCalled()

        toolbarConfigLogic.actions.setOAuthTokens('an-access-token', 'a-refresh-token', 'a-client-id')
        await expectLogic(webVitalsToolbarLogic).toFinishAllListeners()

        expect(webVitalsGet).toHaveBeenCalled()
    })
})
