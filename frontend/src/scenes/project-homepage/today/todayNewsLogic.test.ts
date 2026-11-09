import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { NEW_CHAT_KEY } from '~/layout/ai/attachedContext'
import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TodayNewsApi } from 'products/today/frontend/generated/api.schemas'

import { todayHomeComposerLogic } from './todayHomeComposerLogic'
import { NEWS_POLL_MS, NEWS_REFRESH_MS, todayNewsLogic } from './todayNewsLogic'
import { NEWS_EDITION, NEWS_FRONT_PAGE_EDITION } from './todayTestFixtures'

const COMPUTING: TodayNewsApi = { status: 'computing', skip_reason: null, edition: null }
const READY: TodayNewsApi = { status: 'ready', skip_reason: null, edition: NEWS_EDITION }
const NOT_STARTED: TodayNewsApi = { status: 'not_started', skip_reason: null, edition: NEWS_EDITION }
const WRITING: TodayNewsApi = { ...NOT_STARTED, status: 'computing' }

describe('todayNewsLogic', () => {
    let responses: TodayNewsApi[]
    let writeResponse: TodayNewsApi
    let writeStatus: number
    let writeCalls: number

    beforeEach(() => {
        responses = [READY]
        writeResponse = READY
        writeStatus = 200
        writeCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/today/news/': () => [
                    200,
                    responses.length > 1 ? responses.shift()! : responses[0],
                ],
            },
            post: {
                '/api/projects/:team_id/today/news/write/': () => {
                    writeCalls++
                    return [writeStatus, writeResponse]
                },
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

    it('writes news that is not started once, shows the earlier edition while writing, then swaps in the new one', async () => {
        jest.useFakeTimers()
        responses = [NOT_STARTED, WRITING, { ...READY, edition: NEWS_FRONT_PAGE_EDITION }]
        writeResponse = WRITING
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])

        logic.actions.openNews()
        expect(logic.values.newsStatus).toBe('computing')
        expect(logic.values.writingSince).not.toBeNull()
        await expectLogic(logic).toDispatchActions(['writeNews', 'writeNewsSuccess'])
        logic.actions.closeNews()
        logic.actions.openNews()
        expect(writeCalls).toBe(1)

        jest.advanceTimersByTime(NEWS_POLL_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.newsStatus).toBe('computing')
        expect(logic.values.edition?.id).toBe(NEWS_EDITION.id)

        jest.advanceTimersByTime(NEWS_POLL_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.newsStatus).toBe('ready')
        expect(logic.values.edition?.id).toBe(NEWS_FRONT_PAGE_EDITION.id)
        expect(logic.values.writingSince).toBeNull()
        expect(logic.values.hasUnreadNews).toBe(false)
        expect(writeCalls).toBe(1)
    })

    it('keeps the open news on screen when the first edition fails', async () => {
        jest.useFakeTimers()
        responses = [COMPUTING, { status: 'failed', skip_reason: null, edition: null }]
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        logic.actions.openNews()

        jest.advanceTimersByTime(NEWS_POLL_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.canOpenNews).toBe(false)
        expect(logic.values.showsNewsDialog).toBe(true)

        logic.actions.closeNews()
        expect(logic.values.showsNewsDialog).toBe(false)
    })

    it('says the news is unavailable when the write starts nothing', async () => {
        responses = [{ ...NOT_STARTED, edition: null }]
        writeResponse = { ...NOT_STARTED, edition: null }
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        expect(logic.values.isWriteUnavailable).toBe(false)

        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNewsSuccess'])
        expect(logic.values.newsStatus).toBe('not_started')
        expect(logic.values.isWriteUnavailable).toBe(true)
    })

    it('writes again on the next open after the write request fails, but once per click burst', async () => {
        responses = [NOT_STARTED]
        writeStatus = 500
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])

        logic.actions.openNews()
        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNewsFailure'])
        expect(writeCalls).toBe(1)
        expect(logic.values.newsStatus).toBe('failed')

        logic.actions.closeNews()
        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNews', 'writeNewsFailure'])
        expect(writeCalls).toBe(2)
    })

    it('writes again on the next open after the run fails', async () => {
        jest.useFakeTimers()
        responses = [NOT_STARTED, { status: 'failed', skip_reason: null, edition: NEWS_EDITION }]
        writeResponse = WRITING
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNewsSuccess'])

        jest.advanceTimersByTime(NEWS_POLL_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.newsStatus).toBe('failed')

        logic.actions.closeNews()
        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNews', 'writeNewsSuccess'])
        expect(writeCalls).toBe(2)
    })

    it('writes again when the project day turns over before the browser day', async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-11-09T14:00:00Z'))
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, timezone: 'Asia/Tokyo' })
        responses = [NOT_STARTED, READY, NOT_STARTED]
        writeResponse = WRITING
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNewsSuccess'])

        jest.advanceTimersByTime(NEWS_POLL_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.newsStatus).toBe('ready')
        logic.actions.closeNews()

        jest.advanceTimersByTime(NEWS_REFRESH_MS)
        await expectLogic(logic).toDispatchActions(['loadNews', 'loadNewsSuccess'])
        expect(logic.values.newsStatus).toBe('not_started')
        expect(new Date().toISOString().slice(0, 10)).toBe('2026-11-09')

        logic.actions.openNews()
        await expectLogic(logic).toDispatchActions(['writeNews', 'writeNewsSuccess'])
        expect(writeCalls).toBe(2)
    })

    it.each<[string, TodayNewsApi, boolean]>([
        ['not started without an earlier edition', { ...NOT_STARTED, edition: null }, true],
        ['computing without an earlier edition', COMPUTING, true],
        ['failed over an earlier edition', { status: 'failed', skip_reason: null, edition: NEWS_EDITION }, true],
        ['failed without an earlier edition', { status: 'failed', skip_reason: null, edition: null }, false],
        [
            'skipped because AI data processing is off',
            { status: 'skipped', skip_reason: 'ai_not_approved', edition: null },
            false,
        ],
    ])('offers the news only when there is something to open: %s', async (_, news, canOpenNews) => {
        responses = [news]
        const logic = todayNewsLogic()
        logic.mount()
        expect(logic.values.canOpenNews).toBe(false)

        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        expect(logic.values.canOpenNews).toBe(canOpenNews)
    })

    it('dives into a story by closing the news, attaching the story and prefilling the composer', async () => {
        const logic = todayNewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadNewsSuccess'])
        const story = NEWS_EDITION.stories[1]

        logic.actions.openNews()
        logic.actions.diveIn(story, 2)

        expect(logic.values.isNewsOpen).toBe(false)
        expect(todayHomeComposerLogic.values.composerPrefill).toEqual({ prompt: story.dive_prompt })
        expect(todayHomeComposerLogic.values.composerFocusRequest).toBe(1)
        expect(attachedContextLogic.values.pickedByChat[NEW_CHAT_KEY]).toEqual([
            expect.objectContaining({ type: 'text', label: 'News story', value: `${story.title}. ${story.summary}` }),
        ])

        const next = NEWS_EDITION.stories[2]
        logic.actions.diveIn(next, 3)

        expect(attachedContextLogic.values.pickedByChat[NEW_CHAT_KEY]).toEqual([
            expect.objectContaining({ value: `${next.title}. ${next.summary}` }),
        ])
    })
})
