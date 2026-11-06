import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { NEW_CHAT_KEY } from '~/layout/ai/attachedContext'
import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TodayNewsApi } from 'products/today/frontend/generated/api.schemas'

import { NEWS_POLL_MS, todayNewsLogic } from './todayNewsLogic'
import { NEWS_EDITION } from './todayTestFixtures'

const COMPUTING: TodayNewsApi = { status: 'computing', skip_reason: null, edition: null }
const READY: TodayNewsApi = { status: 'ready', skip_reason: null, edition: NEWS_EDITION }

describe('todayNewsLogic', () => {
    let responses: TodayNewsApi[]

    beforeEach(() => {
        responses = [READY]
        useMocks({
            get: {
                '/api/projects/:team_id/today/news/': () => [
                    200,
                    responses.length > 1 ? responses.shift()! : responses[0],
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('polls while the edition is computing, then shows it as unread until it is opened', async () => {
        jest.useFakeTimers()
        responses = [COMPUTING, READY]
        const logic = todayNewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        expect(logic.values.edition).toBeNull()
        expect(logic.values.hasUnreadNews).toBe(false)

        jest.advanceTimersByTime(NEWS_POLL_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.edition?.id).toBe(NEWS_EDITION.id)
        expect(logic.values.hasUnreadNews).toBe(true)

        logic.actions.openNews()
        expect(logic.values.isNewsOpen).toBe(true)
        expect(logic.values.hasUnreadNews).toBe(false)
    })

    it('dives into a story by closing the news, attaching the story and prefilling the composer', async () => {
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        const story = NEWS_EDITION.stories[1]

        logic.actions.openNews()
        logic.actions.diveIn(story, 2)

        expect(logic.values.isNewsOpen).toBe(false)
        expect(logic.values.composerPrefill).toEqual({ prompt: story.dive_prompt })
        expect(logic.values.composerFocusRequest).toBe(1)
        expect(attachedContextLogic.values.pickedByChat[NEW_CHAT_KEY]).toEqual([
            expect.objectContaining({ type: 'text', label: story.title }),
        ])

        logic.actions.homeTaskStarted('task-1')
        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toMatchObject({ task: 'task-1' })
    })
})
