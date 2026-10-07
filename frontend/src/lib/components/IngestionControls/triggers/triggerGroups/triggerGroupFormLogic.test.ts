import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { triggerGroupFormLogic } from './triggerGroupFormLogic'

describe('triggerGroupFormLogic', () => {
    it.each([
        ['includes a typed pattern that was never added', '/play/.*', ['^/checkout$', '^/play/.*$']],
        ['ignores a typed duplicate', '/checkout', ['^/checkout$']],
        ['does not save an invalid typed regex', '/play/(', null],
    ])('submit %s', async (_, typed, expectedUrls) => {
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

        logic.actions.setNewUrl(typed)
        await expectLogic(logic, () => logic.actions.submitTriggerGroup()).toFinishAllListeners()

        expect(onSave.mock.calls[0]?.[0].conditions.urls.map((u: { url: string }) => u.url) ?? null).toEqual(
            expectedUrls
        )
    })
})
