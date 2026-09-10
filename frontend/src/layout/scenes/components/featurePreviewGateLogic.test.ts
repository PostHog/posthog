import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { featurePreviewGateLogic } from './featurePreviewGateLogic'

describe('featurePreviewGateLogic', () => {
    beforeEach(() => {
        initKeaTests()
        window.localStorage.clear()
    })

    it('confirms straight away when the gate has no probe', async () => {
        const logic = featurePreviewGateLogic({ flag: 'gate-without-probe' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ confirmed: true })
    })

    it('confirms once the server agrees, and caches it for the next mount', async () => {
        const confirmServerAccess = jest.fn().mockResolvedValue(true)

        const logic = featurePreviewGateLogic({ flag: 'gate-confirmed', confirmServerAccess })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ confirmed: true })
        expect(confirmServerAccess).toHaveBeenCalledTimes(1)
        logic.unmount()

        const remounted = featurePreviewGateLogic({ flag: 'gate-confirmed', confirmServerAccess })
        remounted.mount()
        await expectLogic(remounted).toMatchValues({ confirmed: true })
        expect(confirmServerAccess).toHaveBeenCalledTimes(1)
    })

    it('stays unconfirmed while the server still denies access', async () => {
        const confirmServerAccess = jest.fn().mockResolvedValue(false)

        const logic = featurePreviewGateLogic({ flag: 'gate-denied', confirmServerAccess })
        logic.mount()

        await expectLogic(logic).delay(1).toMatchValues({ confirmed: false })
        expect(confirmServerAccess).toHaveBeenCalled()
        expect(window.localStorage.length).toBe(0)
        logic.unmount()
    })

    it('confirms when the probe itself fails, so a broken probe cannot hide the scene', async () => {
        const confirmServerAccess = jest.fn().mockRejectedValue(new Error('network down'))

        const logic = featurePreviewGateLogic({ flag: 'gate-probe-broken', confirmServerAccess })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ confirmed: true })
        expect(confirmServerAccess).toHaveBeenCalledTimes(1)
    })
})
