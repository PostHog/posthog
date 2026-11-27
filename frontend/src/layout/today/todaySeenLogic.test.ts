import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { todaySeenLogic } from './todaySeenLogic'

describe('todaySeenLogic', () => {
    let logic: ReturnType<typeof todaySeenLogic.build>

    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            has_seen_product_intro_for: { seen_on_server: true },
        })
        logic = todaySeenLogic()
        logic.mount()
    })

    test('a key the user record marks seen stays seen, and others are unseen', () => {
        expect(logic.values.isSeen('seen_on_server')).toBe(true)
        expect(logic.values.isSeen('never_seen')).toBe(false)
    })

    test('nothing reads as unseen before the user loads', () => {
        userLogic.actions.loadUserSuccess(null)

        expect(logic.values.isSeen('never_seen')).toBe(true)
    })

    test('marking a key changes it at once, ahead of the user record', () => {
        logic.actions.markSeen('never_seen')
        logic.actions.markUnseen('seen_on_server')

        expect(logic.values.isSeen('never_seen')).toBe(true)
        expect(logic.values.isSeen('seen_on_server')).toBe(false)
    })
})
