import { actions, kea, path, reducers } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { bindModalToUrl } from './bindModalToUrl'
import type { testModalLogicType } from './bindModalToUrl.testType'

// Minimal logic wired to `?modal=test-modal` for exercising bindModalToUrl
const testModalLogic = kea<testModalLogicType>([
    path(['bindModalToUrl', 'test']),
    actions({
        showModal: true,
        hideModal: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
            },
        ],
    }),
    bindModalToUrl({
        urlKey: 'test-modal',
        openActionKey: 'showModal',
        closeActionKey: 'hideModal',
        isOpenKey: 'isOpen',
    }),
])

describe('bindModalToUrl', () => {
    let logic: ReturnType<typeof testModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push('/example')
        logic = testModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('writes the modal key to the URL when the open action fires', async () => {
        await expectLogic(logic, () => {
            logic.actions.showModal()
        }).toMatchValues({ isOpen: true })

        expect(router.values.searchParams.modal).toBe('test-modal')
    })

    it('strips the modal key from the URL when the close action fires', async () => {
        logic.actions.showModal()
        await expectLogic(router).delay(1)
        expect(router.values.searchParams.modal).toBe('test-modal')

        await expectLogic(logic, () => {
            logic.actions.hideModal()
        }).toMatchValues({ isOpen: false })

        expect(router.values.searchParams.modal).toBeUndefined()
    })

    it('opens the modal when the URL already has the matching param on mount (deep link)', async () => {
        logic.unmount()
        router.actions.push('/example', { modal: 'test-modal' })
        logic = testModalLogic()
        logic.mount()

        await expectLogic(logic).delay(1).toMatchValues({ isOpen: true })
    })

    it('closes the modal when the URL param is removed externally (e.g., back/forward navigation)', async () => {
        logic.actions.showModal()
        await expectLogic(router).delay(1)

        router.actions.push('/example')

        await expectLogic(logic).delay(1).toMatchValues({ isOpen: false })
    })

    it('ignores modal params that belong to a different urlKey', async () => {
        router.actions.push('/example', { modal: 'some-other-modal' })

        await expectLogic(logic).delay(1).toMatchValues({ isOpen: false })
    })

    it('preserves unrelated query params when opening and closing', async () => {
        router.actions.push('/example', { tab: 'general', q: 'hello' })
        await expectLogic(router).delay(1)

        logic.actions.showModal()
        await expectLogic(router).delay(1)
        expect(router.values.searchParams).toEqual({ tab: 'general', q: 'hello', modal: 'test-modal' })

        logic.actions.hideModal()
        await expectLogic(router).delay(1)
        expect(router.values.searchParams).toEqual({ tab: 'general', q: 'hello' })
    })

    it('does not re-dispatch when state already matches the URL (loop guard)', async () => {
        await expectLogic(logic, () => {
            logic.actions.showModal()
        })
            .toDispatchActions(['showModal'])
            .toNotHaveDispatchedActions(['showModal', 'showModal'])
    })

    it('does not stomp on another modal key in the URL on close', async () => {
        router.actions.push('/example', { modal: 'unrelated-modal' })
        await expectLogic(router).delay(1)

        logic.actions.hideModal()
        await expectLogic(router).delay(1)
        expect(router.values.searchParams.modal).toBe('unrelated-modal')
    })
})
