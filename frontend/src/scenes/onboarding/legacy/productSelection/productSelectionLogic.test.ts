import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { productSelectionLogic } from './productSelectionLogic'

describe('productSelectionLogic', () => {
    let logic: ReturnType<typeof productSelectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.onboarding())
        logic = productSelectionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('pushes a step query param when advancing past choose_path, so browser Back has an in-app entry to land on', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectPickMyself()
        }).toMatchValues({ currentStep: 'product_selection' })

        expect(router.values.searchParams.step).toEqual('product_selection')
    })

    it('syncs currentStep back to choose_path when the URL loses the step param (browser Back)', async () => {
        logic.actions.selectPickMyself()
        expect(logic.values.currentStep).toEqual('product_selection')

        await expectLogic(logic, () => {
            router.actions.push(urls.onboarding())
        })
            .toDispatchActions(['syncStepFromUrl'])
            .toMatchValues({ currentStep: 'choose_path' })
    })

    it('does not re-dispatch setStep (and re-push the URL) when the URL sync itself fires', async () => {
        await expectLogic(logic, () => {
            logic.actions.selectPickMyself()
        }).toDispatchActions(['setStep'])

        await expectLogic(logic, () => {
            router.actions.push(urls.onboarding())
        }).toNotHaveDispatchedActions(['setStep'])
    })
})
