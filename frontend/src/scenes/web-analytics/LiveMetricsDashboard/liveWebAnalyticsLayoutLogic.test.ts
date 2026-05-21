import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { DEFAULT_CONTENT_ORDER, DEFAULT_STAT_ORDER, LiveContentCardId, LiveStatCardId, mergeOrder } from './liveCards'
import { liveWebAnalyticsLayoutLogic } from './liveWebAnalyticsLayoutLogic'

describe('mergeOrder', () => {
    it.each<{
        name: string
        persisted: LiveStatCardId[]
        expected: LiveStatCardId[]
    }>([
        {
            name: 'returns defaults when persisted is empty',
            persisted: [],
            expected: [...DEFAULT_STAT_ORDER],
        },
        {
            name: 'preserves a persisted order that covers all defaults',
            persisted: ['pageviews', 'users_online', 'unique_visitors'],
            expected: ['pageviews', 'users_online', 'unique_visitors'],
        },
        {
            name: 'drops unknown ids',
            persisted: ['pageviews', 'not_a_card' as LiveStatCardId, 'users_online'],
            expected: ['pageviews', 'users_online', 'unique_visitors'],
        },
        {
            name: 'de-duplicates repeated ids in persisted',
            persisted: ['pageviews', 'pageviews', 'users_online'],
            expected: ['pageviews', 'users_online', 'unique_visitors'],
        },
    ])('$name', ({ persisted, expected }) => {
        expect(mergeOrder(persisted, DEFAULT_STAT_ORDER)).toEqual(expected)
    })

    it('inserts missing default ids while preserving persisted relative order', () => {
        const persisted: LiveContentCardId[] = ['devices', 'browsers']
        const result = mergeOrder(persisted, DEFAULT_CONTENT_ORDER)
        expect(result.indexOf('devices')).toBeLessThan(result.indexOf('browsers'))
        for (const id of DEFAULT_CONTENT_ORDER) {
            expect(result).toContain(id)
        }
        expect(new Set(result).size).toBe(result.length)
    })

    it('inserts a newly-added default next to the preceding persisted neighbor', () => {
        // Pre-`top_countries` persisted order — the new card should slot in between
        // `browsers` and `countries` rather than being appended after `live_events`.
        const persisted: LiveContentCardId[] = [
            'active_users_chart',
            'top_paths',
            'top_referrers',
            'devices',
            'browsers',
            'countries',
            'live_events',
        ]
        expect(mergeOrder(persisted, DEFAULT_CONTENT_ORDER)).toEqual([
            'active_users_chart',
            'top_paths',
            'top_referrers',
            'devices',
            'browsers',
            'top_countries',
            'bot_events_chart',
            'bot_traffic',
            'countries',
            'live_events',
        ])
    })
})

describe('liveWebAnalyticsLayoutLogic', () => {
    let logic: ReturnType<typeof liveWebAnalyticsLayoutLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = liveWebAnalyticsLayoutLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('exposes default orders on mount', async () => {
        await expectLogic(logic).toMatchValues({
            statOrder: [...DEFAULT_STAT_ORDER],
            cardOrder: [...DEFAULT_CONTENT_ORDER],
            isEditing: false,
        })
    })

    it('persists a new stat order and reflects it in the selector', async () => {
        const newOrder: LiveStatCardId[] = ['pageviews', 'users_online', 'unique_visitors']
        await expectLogic(logic, () => {
            logic.actions.setStatOrder(newOrder)
        }).toMatchValues({
            statOrder: newOrder,
        })
    })

    it('persists a new card order', async () => {
        const newOrder: LiveContentCardId[] = [
            'live_events',
            'countries',
            'top_countries',
            'bot_events_chart',
            'bot_traffic',
            'browsers',
            'devices',
            'top_referrers',
            'top_paths',
            'active_users_chart',
        ]
        await expectLogic(logic, () => {
            logic.actions.setCardOrder(newOrder)
        }).toMatchValues({
            cardOrder: newOrder,
        })
    })

    it('self-heals when the persisted order is missing a new default id', async () => {
        const partial: LiveContentCardId[] = ['devices', 'browsers']
        logic.actions.setCardOrder(partial)
        const result = logic.values.cardOrder
        expect(result.indexOf('devices')).toBeLessThan(result.indexOf('browsers'))
        for (const id of DEFAULT_CONTENT_ORDER) {
            expect(result).toContain(id)
        }
        expect(new Set(result).size).toBe(result.length)
    })

    it('toggles edit mode', async () => {
        await expectLogic(logic, () => {
            logic.actions.setEditing(true)
        }).toMatchValues({ isEditing: true })

        await expectLogic(logic, () => {
            logic.actions.setEditing(false)
        }).toMatchValues({ isEditing: false })
    })

    it('resetLayout restores default orders', async () => {
        logic.actions.setStatOrder(['pageviews', 'unique_visitors', 'users_online'])
        logic.actions.setCardOrder(['live_events', 'active_users_chart'] as LiveContentCardId[])

        await expectLogic(logic, () => {
            logic.actions.resetLayout()
        }).toMatchValues({
            statOrder: [...DEFAULT_STAT_ORDER],
            cardOrder: [...DEFAULT_CONTENT_ORDER],
        })
    })
})
