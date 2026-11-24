import { router } from 'kea-router'

import { maxContextLogic } from 'scenes/max/maxContextLogic'
import { PENDING_MAX_CONTEXT_KEY } from 'scenes/max/maxLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import type { EventDefinition } from '~/types'

import { todayHomeClassicComposerLogic } from './todayHomeClassicComposerLogic'

describe('todayHomeClassicComposerLogic', () => {
    beforeEach(() => {
        initKeaTests()
        sessionStorage.clear()
    })

    it('opens a PostHog AI chat that asks the prompt in the picked mode', () => {
        const logic = todayHomeClassicComposerLogic()
        logic.mount()
        logic.actions.setPrompt('  Why did sign-ups drop?  ')
        logic.actions.setMode(AgentMode.SQL)

        logic.actions.chatStarted(logic.values.prompt)

        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toEqual({ ask: 'Why did sign-ups drop?', mode: AgentMode.SQL })
        expect(logic.values.prompt).toEqual('')
        expect(sessionStorage.getItem(PENDING_MAX_CONTEXT_KEY)).toBeNull()
    })

    it('gives the picked context to the chat before the route change clears it', () => {
        const logic = todayHomeClassicComposerLogic()
        logic.mount()
        maxContextLogic.actions.addOrUpdateContextEvent({ id: 'event-1', name: '$pageview' } as EventDefinition)

        logic.actions.chatStarted('What happened?')

        expect(router.values.searchParams).toEqual({ ask: 'What happened?' })
        expect(JSON.parse(sessionStorage.getItem(PENDING_MAX_CONTEXT_KEY) ?? '{}').context).toMatchObject({
            events: [expect.objectContaining({ name: '$pageview' })],
        })
    })
})
