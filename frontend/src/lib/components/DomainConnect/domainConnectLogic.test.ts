import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { domainConnectLogic } from './domainConnectLogic'

const APPLY_URL = 'https://dash.cloudflare.com/domainconnect/apply?x=1'

describe('domainConnectLogic', () => {
    let logic: ReturnType<typeof domainConnectLogic.build>
    let openSpy: jest.SpyInstance
    let fakeTab: { location: { href: string }; opener: unknown; close: jest.Mock }

    beforeEach(() => {
        fakeTab = { location: { href: '' }, opener: {}, close: jest.fn() }
        openSpy = jest.spyOn(window, 'open').mockReturnValue(fakeTab as unknown as Window)
        useMocks({
            post: {
                '/api/environments/:team_id/integrations/domain-connect/apply-url': () => [200, { url: APPLY_URL }],
            },
        })
        initKeaTests()
        logic = domainConnectLogic({ logicKey: 'test', domain: null, context: 'email', integrationId: 7 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        openSpy.mockRestore()
    })

    it('opens the tab synchronously, then navigates it once the apply URL resolves', async () => {
        logic.actions.openDomainConnect()

        // The tab must open within the click's synchronous call stack — before the awaited
        // apply-URL request — or the browser blocks it as a popup (the dead-click bug).
        expect(openSpy).toHaveBeenCalledWith('about:blank', '_blank')
        expect(fakeTab.location.href).toBe('')

        await expectLogic(logic).toDispatchActions(['setIsApplying', 'setIsApplying']).toMatchValues({
            isApplying: false,
        })

        expect(fakeTab.location.href).toBe(APPLY_URL)
    })

    it('closes the opened tab and stops loading when the apply URL request fails', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/integrations/domain-connect/apply-url': () => [400, { detail: 'nope' }],
            },
        })

        logic.actions.openDomainConnect()

        await expectLogic(logic).toDispatchActions(['setIsApplying', 'setIsApplying']).toMatchValues({
            isApplying: false,
        })

        expect(fakeTab.close).toHaveBeenCalled()
        expect(fakeTab.location.href).toBe('')
    })
})
