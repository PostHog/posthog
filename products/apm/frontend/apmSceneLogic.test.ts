import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { DEFAULT_APM_TAB, apmSceneLogic } from './apmSceneLogic'

describe('apmSceneLogic', () => {
    let logic: ReturnType<typeof apmSceneLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = apmSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens on the logs facet', () => {
        expect(logic.values.activeTab).toEqual(DEFAULT_APM_TAB)
        expect(logic.values.activeTab).toEqual('logs')
    })

    it.each([['logs'], ['traces'], ['metrics']])('selects the %s facet from the tab param', async (tab) => {
        await expectLogic(logic, () => {
            router.actions.push('/apm', { tab })
        }).toFinishAllListeners()

        expect(logic.values.activeTab).toEqual(tab)
    })

    it('falls back to the default facet for an unknown tab param', async () => {
        // A stale or hand-edited link must not strand the scene on a facet that renders nothing.
        await expectLogic(logic, () => {
            router.actions.push('/apm', { tab: 'not-a-facet' })
        }).toFinishAllListeners()

        expect(logic.values.activeTab).toEqual(DEFAULT_APM_TAB)
    })

    it('round-trips the facet through the URL, leaving the default implicit', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab('traces')
        }).toFinishAllListeners()
        expect(router.values.searchParams.tab).toEqual('traces')

        await expectLogic(logic, () => {
            logic.actions.setActiveTab(DEFAULT_APM_TAB)
        }).toFinishAllListeners()
        expect(router.values.searchParams.tab).toBeUndefined()
    })

    it('keeps the shared scope when switching facet', async () => {
        // The shared scope is what makes the three facets read as one product: narrow to a
        // service and a window on logs, switch to traces, and you are still looking at the same
        // service over the same window.
        await expectLogic(logic, () => {
            logic.actions.setDateRange({ date_from: '-24h', date_to: null })
            logic.actions.setServiceNames(['checkout-api'])
            logic.actions.setActiveTab('traces')
        }).toFinishAllListeners()

        expect(logic.values.activeTab).toEqual('traces')
        expect(logic.values.dateRange).toEqual({ date_from: '-24h', date_to: null })
        expect(logic.values.serviceNames).toEqual(['checkout-api'])
    })

    it.each([
        ['JSON array', '["checkout-api","payments-worker"]', ['checkout-api', 'payments-worker']],
        ['comma separated', 'checkout-api,payments-worker', ['checkout-api', 'payments-worker']],
    ])('reads the service scope from a %s param', async (_name, param, expected) => {
        await expectLogic(logic, () => {
            router.actions.push('/apm', { serviceNames: param })
        }).toFinishAllListeners()

        expect(logic.values.serviceNames).toEqual(expected)
    })
})
