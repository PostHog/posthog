import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { prepareUrlPattern, triggerGroupFormLogic } from './triggerGroupFormLogic'

describe('triggerGroupFormLogic', () => {
    let logic: ReturnType<typeof triggerGroupFormLogic.build>
    let onSave: jest.Mock

    beforeEach(() => {
        initKeaTests()
        onSave = jest.fn()
        logic = triggerGroupFormLogic({
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
    })

    it.each([
        ['empty input', '  ', { error: 'empty' }],
        ['invalid regex', '/play/(', { error: 'invalid' }],
        ['duplicate after anchoring', '/checkout', { error: 'duplicate' }],
        ['new pattern is anchored', '/play/.*', { url: '^/play/.*$' }],
    ])('prepareUrlPattern: %s', (_, raw, expected) => {
        expect(prepareUrlPattern(raw, [{ url: '^/checkout$', matching: 'regex' }])).toEqual(expected)
    })

    it.each([
        ['saves a typed pattern that was never added', '/play/.*', ['^/checkout$', '^/play/.*$']],
        ['ignores a typed duplicate', '/checkout', ['^/checkout$']],
        ['saves as before when the input is empty', '', ['^/checkout$']],
    ])('submit %s', async (_, typed, expectedUrls) => {
        logic.actions.setNewUrl(typed)
        await expectLogic(logic, () => logic.actions.submitTriggerGroup()).toFinishAllListeners()

        expect(onSave).toHaveBeenCalledTimes(1)
        expect(onSave.mock.calls[0][0].conditions.urls.map((u: { url: string }) => u.url)).toEqual(expectedUrls)
    })

    it('does not save when the typed pattern is an invalid regex', async () => {
        logic.actions.setNewUrl('/play/(')
        await expectLogic(logic, () => logic.actions.submitTriggerGroup()).toFinishAllListeners()

        expect(onSave).not.toHaveBeenCalled()
    })

    it('saves a pattern added with the inner Add button', async () => {
        logic.actions.addUrl('/play/.*')
        await expectLogic(logic, () => logic.actions.submitTriggerGroup()).toFinishAllListeners()

        expect(onSave.mock.calls[0][0].conditions.urls.map((u: { url: string }) => u.url)).toEqual([
            '^/checkout$',
            '^/play/.*$',
        ])
    })
})
