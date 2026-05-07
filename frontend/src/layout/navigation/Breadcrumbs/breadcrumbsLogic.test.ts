import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { breadcrumbsLogic } from './breadcrumbsLogic'

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.SavedInsights]: blankScene, [Scene.Dashboards]: blankScene }

describe('breadcrumbsLogic', () => {
    let logic: ReturnType<typeof breadcrumbsLogic.build>

    beforeEach(async () => {
        initKeaTests()
        sceneLogic({ scenes }).mount()
    })

    it('sets document.title when page is visible', async () => {
        expect(global.document.title).toEqual('')

        logic = breadcrumbsLogic()
        logic.mount()

        // test with .delay because subscriptions happen async
        router.actions.push(urls.savedInsights())
        await expectLogic(logic).delay(1).toMatchValues({ documentTitle: 'Product analytics • PostHog' })
        expect(global.document.title).toEqual('Product analytics • PostHog')

        router.actions.push(urls.dashboards())
        await expectLogic(logic).delay(1).toMatchValues({ documentTitle: 'Dashboards • PostHog' })
        expect(global.document.title).toEqual('Dashboards • PostHog')
    })

    it('defers document.title update when page is hidden', async () => {
        logic = breadcrumbsLogic()
        logic.mount()

        router.actions.push(urls.savedInsights())
        await expectLogic(logic).delay(1).toMatchValues({ documentTitle: 'Product analytics • PostHog' })
        expect(global.document.title).toEqual('Product analytics • PostHog')

        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden', writable: true })

        router.actions.push(urls.dashboards())
        await expectLogic(logic).delay(1).toMatchValues({ documentTitle: 'Dashboards • PostHog' })
        expect(global.document.title).toEqual('Product analytics • PostHog')

        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible', writable: true })
        document.dispatchEvent(new Event('visibilitychange'))

        expect(global.document.title).toEqual('Dashboards • PostHog')
    })

    it('does not update the default document.title while hidden during startup', async () => {
        global.document.title = 'PostHog'
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden', writable: true })

        logic = breadcrumbsLogic()
        logic.mount()

        router.actions.push(urls.savedInsights())
        await expectLogic(logic).delay(1).toMatchValues({ documentTitle: 'Product analytics • PostHog' })
        expect(global.document.title).toEqual('PostHog')

        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible', writable: true })
        document.dispatchEvent(new Event('visibilitychange'))

        expect(global.document.title).toEqual('Product analytics • PostHog')
    })
})
