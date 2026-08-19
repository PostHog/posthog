import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { triggerGroupFormLogic } from './triggerGroupFormLogic'

describe('triggerGroupFormLogic', () => {
    let logic: ReturnType<typeof triggerGroupFormLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = triggerGroupFormLogic({ onSave: jest.fn(), onCancel: jest.fn() })
        logic.mount()
    })

    it('keeps the typed pattern and open panel when a rejected pattern is added', async () => {
        await expectLogic(logic, () => {
            logic.actions.setIsAddingUrl(true)
            logic.actions.setNewUrl('[') // invalid regex
            logic.actions.addUrl('[')
        }).toMatchValues({
            newUrl: '[',
            isAddingUrl: true,
            newUrlError: 'Invalid regex pattern. Please check your syntax.',
        })
        expect(logic.values.triggerGroup.urls).toEqual([])
    })

    it('reports a duplicate pattern without clearing the field', async () => {
        await expectLogic(logic, () => {
            logic.actions.addUrl('/checkout')
            logic.actions.setNewUrl('/checkout')
            logic.actions.addUrl('/checkout')
        }).toMatchValues({
            newUrl: '/checkout',
            isAddingUrl: false,
            newUrlError: 'This URL pattern has already been added',
        })
        expect(logic.values.triggerGroup.urls).toEqual([{ url: '^/checkout$', matching: 'regex' }])
    })

    it('anchors, clears the field and closes the panel on a successful add', async () => {
        await expectLogic(logic, () => {
            logic.actions.setIsAddingUrl(true)
            logic.actions.setNewUrl('/checkout')
            logic.actions.addUrl('/checkout')
        }).toMatchValues({
            newUrl: '',
            isAddingUrl: false,
            newUrlError: null,
        })
        expect(logic.values.triggerGroup.urls).toEqual([{ url: '^/checkout$', matching: 'regex' }])
    })
})
