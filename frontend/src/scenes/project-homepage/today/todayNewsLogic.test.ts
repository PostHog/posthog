import { router } from 'kea-router'

import { NEW_CHAT_KEY } from '~/layout/ai/attachedContext'
import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { initKeaTests } from '~/test/init'

import { todayNewsLogic } from './todayNewsLogic'

describe('todayNewsLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('clears the unread dot when the news opens, and keeps it closed until a new edition', () => {
        const logic = todayNewsLogic()
        logic.mount()

        expect(logic.values.hasUnreadNews).toBe(true)
        logic.actions.openNews()
        expect(logic.values.isNewsOpen).toBe(true)
        expect(logic.values.hasUnreadNews).toBe(false)

        logic.actions.markEditionRead(String(logic.values.currentProjectId), 'an-older-edition')
        expect(logic.values.hasUnreadNews).toBe(true)
    })

    it('dives into a story by closing the news, attaching the story and prefilling the composer', () => {
        const logic = todayNewsLogic()
        logic.mount()
        const story = logic.values.edition.stories[1]

        logic.actions.openNews()
        logic.actions.diveIn(story, 2)

        expect(logic.values.isNewsOpen).toBe(false)
        expect(logic.values.composerPrefill).toEqual({ prompt: story.divePrompt })
        expect(logic.values.composerFocusRequest).toBe(1)
        expect(attachedContextLogic.values.pickedByChat[NEW_CHAT_KEY]).toEqual([
            expect.objectContaining({ type: 'text', label: story.title }),
        ])

        logic.actions.homeTaskStarted('task-1')
        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toMatchObject({ task: 'task-1' })
    })
})
