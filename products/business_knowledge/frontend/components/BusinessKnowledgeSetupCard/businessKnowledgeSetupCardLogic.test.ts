import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { businessKnowledgeLogic } from '../../scenes/sources/businessKnowledgeLogic'
import { businessKnowledgeSetupCardLogic } from './businessKnowledgeSetupCardLogic'

describe('businessKnowledgeSetupCardLogic', () => {
    let logic: ReturnType<typeof businessKnowledgeSetupCardLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/business_knowledge/sources/': { count: 0, results: [] },
                '/api/projects/:team_id/business_knowledge/libraries/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        logic = businessKnowledgeSetupCardLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([['url'], ['file'], ['text']] as const)('opens the create modal on the %s tab', async (source) => {
        logic.actions.pickSource(source, 'needs-setup', false)
        await expectLogic(logic).toFinishAllListeners()

        expect(businessKnowledgeLogic.values.isCreateModalOpen).toBe(true)
        expect(businessKnowledgeLogic.values.createTab).toBe(source)
    })

    it.each([
        ['github', 'business-knowledge-github-repos'],
        ['support', 'business-knowledge-learn-from-support'],
    ] as const)('opens the %s setting in business knowledge settings', async (source, settingId) => {
        logic.actions.pickSource(source, 'needs-setup', false)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain('/business-knowledge/settings')
        expect(router.values.hashParams).toEqual({ selectedSetting: settingId })
        expect(businessKnowledgeLogic.values.isCreateModalOpen).toBe(false)
    })
})
