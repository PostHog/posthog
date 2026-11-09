import { initKeaTests } from '~/test/init'

import { dashboardAiPromptComposerLogic } from './dashboardAiPromptComposerLogic'

describe('dashboardAiPromptComposerLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('starts with an empty prompt', () => {
        dashboardAiPromptComposerLogic.mount()

        expect(dashboardAiPromptComposerLogic.values.prompt).toBe('')
    })
})
