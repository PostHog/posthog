import { initKeaTests } from '~/test/init'

import { sessionConversationOptionsLogic } from './sessionConversationOptionsLogic'

describe('sessionConversationOptionsLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('stores the choice under the key everyone already has', () => {
        const logic = sessionConversationOptionsLogic()
        logic.mount()

        logic.actions.setConversationOnly(true)

        expect(localStorage.getItem('ai_observability.session_conversation_only')).toEqual('true')
        logic.unmount()
    })
})
