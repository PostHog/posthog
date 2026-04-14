import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { DEFAULT_CONTENT_ORDER, DEFAULT_STAT_ORDER, LiveContentCardId, LiveStatCardId, mergeOrder } from './liveCards'
import { liveWebAnalyticsLayoutLogic } from './liveWebAnalyticsLayoutLogic'

describe('mergeOrder', () => {
    it('returns defaults when persisted is empty', () => {
        expect(mergeOrder<LiveStatCardId>([], DEFAULT_STAT_ORDER)).toEqual([...DEFAULT_STAT_ORDER])
    })

    it('preserves a persisted order that covers all defaults', () => {
        const reordered: LiveStatCardId[] = ['pageviews', 'users_online', 'unique_visitors']
        expect(mergeOrder(reordered, DEFAULT_STAT_ORDER)).toEqual(reordered)
    })

    it('drops unknown ids', () => {
        const persisted = ['pageviews', 'not_a_card', 'users_online'] as LiveStatCardId[]
        expect(mergeOrder(persisted, DEFAULT_STAT_ORDER)).toEqual(['pageviews', 'users_online', 'unique_visitors'])
    })

    it('appends missing default ids at the end', () => {
        const persisted: LiveContentCardId[] = ['devices', 'browsers']
        const result = mergeOrder(persisted, DEFAULT_CONTENT_ORDER)
        expect(result.slice(0, 2)).toEqual(['devices', 'browsers'])
        // Every default id should be present
        for (const id of DEFAULT_CONTENT_ORDER) {
            expect(result).toContain(id)
        }
        // No duplicates
        expect(new Set(result).size).toBe(result.length)
    })

    it('de-duplicates repeated ids in persisted', () => {
        const persisted: LiveStatCardId[] = ['pageviews', 'pageviews', 'users_online']
        expect(mergeOrder(persisted, DEFAULT_STAT_ORDER)).toEqual(['pageviews', 'users_online', 'unique_visitors'])
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
        expect(result.slice(0, 2)).toEqual(['devices', 'browsers'])
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
