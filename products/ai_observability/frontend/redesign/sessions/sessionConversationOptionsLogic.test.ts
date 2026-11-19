import { initKeaTests } from '~/test/init'

import { sessionConversationOptionsLogic } from './sessionConversationOptionsLogic'

describe('sessionConversationOptionsLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('conversation only persists', () => {
        const logic = sessionConversationOptionsLogic()
        logic.mount()
        expect(logic.values.conversationOnly).toBe(false)

        logic.actions.setConversationOnly(true)
        logic.unmount()
        initKeaTests()
        const remounted = sessionConversationOptionsLogic()
        remounted.mount()

        expect(remounted.values.conversationOnly).toBe(true)
        expect(localStorage.getItem('ai_observability.session_conversation_only')).toEqual('true')
        remounted.unmount()
    })
})
