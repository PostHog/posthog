import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ElementsEventType } from '~/toolbar/types'

import { dedupeByChainIdentity, heatmapToolbarMenuLogic } from './heatmapToolbarMenuLogic'

function statsRow(overrides: Partial<ElementsEventType>): ElementsEventType {
    return {
        count: 1,
        hash: null,
        type: '$autocapture',
        elements: [{ tag_name: 'button', attr_class: ['btn'], nth_child: 1, nth_of_type: 1, attributes: {} }],
        ...overrides,
    } as ElementsEventType
}

describe('heatmapToolbarMenuLogic', () => {
    describe('dedupeByChainIdentity', () => {
        const cases = [
            {
                name: 'keeps distinct chains when a legacy server returns hash null',
                events: [
                    statsRow({ elements: [{ tag_name: 'button', attributes: {} }] as ElementsEventType['elements'] }),
                    statsRow({ elements: [{ tag_name: 'a', attributes: {} }] as ElementsEventType['elements'] }),
                ],
                expectedCount: 2,
            },
            {
                name: 'drops a null-hash chain repeated across paginated pages, keeping the first occurrence',
                events: [statsRow({ count: 10 }), statsRow({ count: 3 })],
                expectedCount: 1,
            },
            {
                name: 'keeps identical chains that differ by event type',
                events: [statsRow({ type: '$autocapture' }), statsRow({ type: '$rageclick' })],
                expectedCount: 2,
            },
            {
                name: 'keeps distinct hashes even when attribute trimming made the chains serialize identically',
                events: [statsRow({ hash: 'abc123' }), statsRow({ hash: 'def456' })],
                expectedCount: 2,
            },
            {
                name: 'drops a repeated hash across paginated pages, keeping the first occurrence',
                events: [statsRow({ hash: 'abc123', count: 10 }), statsRow({ hash: 'abc123', count: 3 })],
                expectedCount: 1,
            },
        ]

        it.each(cases)('$name', ({ events, expectedCount }) => {
            expect(dedupeByChainIdentity(events)).toHaveLength(expectedCount)
        })

        it('keeps the first occurrence of a duplicated chain', () => {
            const [kept] = dedupeByChainIdentity([statsRow({ count: 10 }), statsRow({ count: 3 })])
            expect(kept.count).toBe(10)
        })
    })

    describe('clickmap loading', () => {
        let logic: ReturnType<typeof heatmapToolbarMenuLogic.build>

        beforeEach(() => {
            global.IntersectionObserver = class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            } as any
            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve({ results: [] }),
                } as any as Response)
            )
            jest.spyOn(toolbarApi.elementStats, 'list').mockResolvedValue({
                ok: true,
                status: 200,
                data: { results: [], next: null, previous: null },
            } as any)

            initKeaTests()
            toolbarConfigLogic
                .build({
                    apiURL: 'http://localhost',
                    accessToken: 'test-token',
                    refreshToken: 'test-refresh',
                    clientId: 'test-client',
                })
                .mount()
            logic = heatmapToolbarMenuLogic()
            logic.mount()
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('loads element stats as soon as the heatmap menu opens, without toggling clickmaps', async () => {
            await expectLogic(logic, () => logic.actions.enableHeatmap()).toDispatchActions([
                'getElementStats',
                'getElementStatsSuccess',
            ])
            expect(toolbarApi.elementStats.list).toHaveBeenCalled()
        })

        it('does not fetch element stats on navigation while the heatmap menu is closed', async () => {
            await expectLogic(logic, () =>
                logic.actions.setHref('https://example.com/other')
            ).toNotHaveDispatchedActions(['getElementStats'])
            expect(toolbarApi.elementStats.list).not.toHaveBeenCalled()
        })

        it('fetches element stats on navigation while the heatmap menu is open', async () => {
            await expectLogic(logic, () => logic.actions.enableHeatmap()).toDispatchActions(['getElementStats'])
            await expectLogic(logic, () => logic.actions.setHref('https://example.com/other')).toDispatchActions([
                'getElementStats',
            ])
        })

        it('does not fetch element stats when clickmaps are toggled off while the request is debouncing', async () => {
            await expectLogic(logic, () => {
                logic.actions.enableHeatmap()
                logic.actions.toggleClickmapsEnabled(false)
            }).toDispatchActions(['getElementStats', 'getElementStatsSuccess'])
            expect(toolbarApi.elementStats.list).not.toHaveBeenCalled()
        })

        it('keeps heatmapEnabled true after a stats fetch failure so the menu stays open', async () => {
            jest.spyOn(toolbarApi.elementStats, 'list').mockRejectedValue(new Error('network error'))
            await expectLogic(logic, () => logic.actions.enableHeatmap()).toDispatchActions([
                'getElementStats',
                'getElementStatsFailure',
            ])
            expect(logic.values.heatmapEnabled).toBe(true)
        })

        it('retries the initial load via load more after a stats fetch failure', async () => {
            jest.spyOn(toolbarApi.elementStats, 'list').mockRejectedValueOnce(new Error('network error'))
            await expectLogic(logic, () => logic.actions.enableHeatmap()).toDispatchActions(['getElementStatsFailure'])
            await expectLogic(logic, () => logic.actions.loadMoreElementStats()).toDispatchActions([
                'getElementStats',
                'getElementStatsSuccess',
            ])
            expect(toolbarApi.elementStats.list).toHaveBeenCalledTimes(2)
        })
    })
})
