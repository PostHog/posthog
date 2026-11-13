import { router } from 'kea-router'

import { PENDING_AI_PROMPT_KEY } from '~/layout/ai/pendingAiPrompt'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { initKeaTests } from '~/test/init'

import { TODAY_HOME_PANEL_ID, todayHomeComposerLogic } from './todayHomeComposerLogic'

describe('todayHomeComposerLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('opens the task that the home composer started', () => {
        const logic = todayHomeComposerLogic()
        logic.mount()

        logic.actions.homeTaskStarted('task-1')

        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toMatchObject({ task: 'task-1' })
    })

    it('opens a PostHog AI chat that asks the home prompt when the person has no task runtime', () => {
        const logic = todayHomeComposerLogic()
        logic.mount()
        logic.actions.setClassicPrompt('  Why did sign-ups drop?  ')

        logic.actions.classicChatStarted(logic.values.classicPrompt)

        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toMatchObject({ ask: 'Why did sign-ups drop?' })
        expect(logic.values.classicPrompt).toEqual('')
    })

    it('keeps the prompt and opens classic PostHog AI when the server refuses a new task', () => {
        todayHomeComposerLogic().mount()

        runnerPanelLogic({ panelId: TODAY_HOME_PANEL_ID }).actions.handOffToClassic('Why did sign-ups drop?')

        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(JSON.parse(sessionStorage.getItem(PENDING_AI_PROMPT_KEY) ?? '{}')).toMatchObject({
            prompt: 'Why did sign-ups drop?',
        })
    })
})
