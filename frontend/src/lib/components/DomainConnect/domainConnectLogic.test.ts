import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { domainConnectLogic } from './domainConnectLogic'

const APPLY_URL = 'https://dns.example.com/v2/domainTemplates/providers/posthog.com/services/proxy/apply?sig=fake'
const APPLY_URL_ENDPOINT = '/api/environments/:team_id/integrations/domain-connect/apply-url/'

interface FakeProviderTab {
    opener: unknown
    location: { href: string }
    close: jest.Mock
}

describe('domainConnectLogic', () => {
    const originalLocation = window.location
    let logic: ReturnType<typeof domainConnectLogic.build>
    let providerTab: FakeProviderTab

    function useApplyUrlResponse(status: number, body: Record<string, unknown>): void {
        useMocks({ post: { [APPLY_URL_ENDPOINT]: () => [status, body] } })
    }

    beforeEach(() => {
        useApplyUrlResponse(200, { url: APPLY_URL })
        initKeaTests()
        providerTab = { opener: window, location: { href: '' }, close: jest.fn() }
        jest.spyOn(window, 'open').mockReturnValue(providerTab as unknown as Window)
        Object.defineProperty(window, 'location', {
            value: { ...originalLocation, assign: jest.fn() },
            configurable: true,
        })
        logic = domainConnectLogic({ logicKey: 'test', domain: null, context: 'proxy', proxyRecordId: 'record-1' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
        jest.restoreAllMocks()
    })

    it('opens the provider tab during the tap, because mobile Safari blocks a tab opened after a request', async () => {
        logic.actions.openDomainConnect()
        expect(window.open).toHaveBeenCalledTimes(1)

        await expectLogic(logic).toFinishAllListeners()

        expect(providerTab.location.href).toEqual(APPLY_URL)
        expect(providerTab.opener).toBeNull()
        expect(window.location.assign).not.toHaveBeenCalled()
    })

    it('falls back to the current tab when the browser refuses to open a new one', async () => {
        jest.mocked(window.open).mockReturnValue(null)

        logic.actions.openDomainConnect()
        await expectLogic(logic).toFinishAllListeners()

        expect(window.location.assign).toHaveBeenCalledWith(APPLY_URL)
    })

    it('closes the blank provider tab when the apply URL request fails', async () => {
        useApplyUrlResponse(400, { detail: 'Proxy record not found' })

        logic.actions.openDomainConnect()
        await expectLogic(logic).toFinishAllListeners()

        expect(providerTab.close).toHaveBeenCalled()
        expect(providerTab.location.href).toEqual('')
    })
})
