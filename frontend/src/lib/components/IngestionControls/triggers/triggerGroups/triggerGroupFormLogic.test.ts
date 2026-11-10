import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { triggerGroupFormLogic } from './triggerGroupFormLogic'

describe('triggerGroupFormLogic', () => {
    it.each([
        ['includes a typed pattern that was never added', '/play/.*', false, ['^/checkout$', '^/play/.*$']],
        ['ignores a typed duplicate', '/checkout', false, ['^/checkout$']],
        ['does not save an invalid typed regex', '/play/(', false, null],
        ['drops a typed pattern after the URL editor is canceled', '/play/.*', true, ['^/checkout$']],
        ['drops an invalid typed regex after the URL editor is canceled', '/play/(', true, ['^/checkout$']],
    ])('submit %s', async (_, typed, canceled, expectedUrls) => {
        initKeaTests()
        const onSave = jest.fn()
        const logic = triggerGroupFormLogic({
            group: {
                id: 'group-1',
                name: 'Checkout',
                sampleRate: 1,
                conditions: { matchType: 'any', urls: [{ url: '^/checkout$', matching: 'regex' }] },
            },
            onSave,
            onCancel: jest.fn(),
        })
        logic.mount()

        logic.actions.setIsAddingUrl(true)
        logic.actions.setNewUrl(typed)
        if (canceled) {
            logic.actions.setIsAddingUrl(false)
        }
        await expectLogic(logic, () => logic.actions.submitTriggerGroup()).toFinishAllListeners()

        expect(onSave.mock.calls[0]?.[0].conditions.urls.map((u: { url: string }) => u.url) ?? null).toEqual(
            expectedUrls
        )
    })
})
