import { dayjs } from 'lib/dayjs'

import { compareTimelineItems, ItemCategory, ItemCollector, ItemLoader, ItemRenderer, TimelineItem } from '.'

const renderer: ItemRenderer<TimelineItem> = {
    sourceIcon: () => null,
    categoryIcon: null,
    render: () => null,
}

function createItem(id: string, category: ItemCategory, timestamp: string): TimelineItem {
    return {
        id,
        category,
        timestamp: dayjs.utc(timestamp),
        payload: {},
    }
}

function createInMemoryLoader(items: TimelineItem[]): ItemLoader<TimelineItem> {
    return {
        loadBefore: jest.fn(async (cursor: dayjs.Dayjs, limit: number) => {
            const available = items
                .filter((item) => item.timestamp.isBefore(cursor))
                .sort((a, b) => compareTimelineItems(b, a))
            return {
                items: available.slice(0, limit),
                hasMoreBefore: available.length > limit,
            }
        }),
        loadAfter: jest.fn(async (cursor: dayjs.Dayjs, limit: number) => {
            const available = items.filter((item) => item.timestamp.isAfter(cursor)).sort(compareTimelineItems)
            return {
                items: available.slice(0, limit),
                hasMoreAfter: available.length > limit,
            }
        }),
    }
}

describe('ItemCollector', () => {
    it('stops querying exhausted loaders for subsequent before loads', async () => {
        const exhaustedLoader: ItemLoader<TimelineItem> = {
            loadBefore: jest
                .fn()
                .mockResolvedValueOnce({ items: [], hasMoreBefore: false })
                .mockResolvedValueOnce({
                    items: [createItem('should-not-be-fetched', ItemCategory.PAGE_VIEWS, '2024-07-09T11:58:00Z')],
                    hasMoreBefore: true,
                }),
            loadAfter: jest.fn().mockResolvedValue({ items: [], hasMoreAfter: false }),
        }

        const activeLoader: ItemLoader<TimelineItem> = {
            loadBefore: jest
                .fn()
                .mockResolvedValueOnce({
                    items: [
                        createItem('active-1', ItemCategory.CUSTOM_EVENTS, '2024-07-09T11:59:00Z'),
                        createItem('active-1b', ItemCategory.CUSTOM_EVENTS, '2024-07-09T11:58:45Z'),
                    ],
                    hasMoreBefore: true,
                })
                .mockResolvedValueOnce({
                    items: [
                        createItem('active-2', ItemCategory.CUSTOM_EVENTS, '2024-07-09T11:58:30Z'),
                        createItem('active-2b', ItemCategory.CUSTOM_EVENTS, '2024-07-09T11:58:15Z'),
                    ],
                    hasMoreBefore: true,
                }),
            loadAfter: jest.fn().mockResolvedValue({ items: [], hasMoreAfter: false }),
        }

        const collector = new ItemCollector('session-id', dayjs.utc('2024-07-09T12:00:00Z'))
        collector.addCategory(ItemCategory.PAGE_VIEWS, renderer, exhaustedLoader)
        collector.addCategory(ItemCategory.CUSTOM_EVENTS, renderer, activeLoader)

        await collector.loadBefore(4)
        await collector.loadBefore(4)

        expect(exhaustedLoader.loadBefore).toHaveBeenCalledTimes(1)
        expect(activeLoader.loadBefore).toHaveBeenCalledTimes(2)
    })

    it('resets loader directional exhaustion when collector is cleared', async () => {
        const loader: ItemLoader<TimelineItem> = {
            loadBefore: jest
                .fn()
                .mockResolvedValueOnce({ items: [], hasMoreBefore: false })
                .mockResolvedValueOnce({
                    items: [createItem('after-clear', ItemCategory.ERROR_TRACKING, '2024-07-09T11:59:00Z')],
                    hasMoreBefore: true,
                }),
            loadAfter: jest.fn().mockResolvedValue({ items: [], hasMoreAfter: false }),
        }

        const collector = new ItemCollector('session-id', dayjs.utc('2024-07-09T12:00:00Z'))
        collector.addCategory(ItemCategory.ERROR_TRACKING, renderer, loader)

        await collector.loadBefore(1)
        expect(loader.loadBefore).toHaveBeenCalledTimes(1)
        expect(collector.hasMoreBefore).toBe(false)

        collector.clear()

        await collector.loadBefore(1)
        expect(loader.loadBefore).toHaveBeenCalledTimes(2)
        expect(collector.hasMoreBefore).toBe(true)
    })

    it('respects explicit hasMore flags from loaders', async () => {
        const loader: ItemLoader<TimelineItem> = {
            loadBefore: jest
                .fn()
                .mockResolvedValueOnce({
                    items: [createItem('one-last-item', ItemCategory.ERROR_TRACKING, '2024-07-09T11:59:00Z')],
                    hasMoreBefore: false,
                })
                .mockResolvedValueOnce({
                    items: [createItem('should-not-be-called', ItemCategory.ERROR_TRACKING, '2024-07-09T11:58:00Z')],
                    hasMoreBefore: true,
                }),
            loadAfter: jest.fn().mockResolvedValue({ items: [], hasMoreAfter: false }),
        }

        const collector = new ItemCollector('session-id', dayjs.utc('2024-07-09T12:00:00Z'))
        collector.addCategory(ItemCategory.ERROR_TRACKING, renderer, loader)

        await collector.loadBefore(10)
        expect(collector.hasMoreBefore).toBe(false)

        await collector.loadBefore(10)
        expect(loader.loadBefore).toHaveBeenCalledTimes(1)
    })

    it('keeps before pagination overlapping equal timestamps by 1 ms', async () => {
        const loader = createInMemoryLoader([
            createItem('newest', ItemCategory.ERROR_TRACKING, '2024-07-09T12:00:05.000Z'),
            createItem('same-ts-a', ItemCategory.ERROR_TRACKING, '2024-07-09T12:00:03.000Z'),
            createItem('same-ts-b', ItemCategory.ERROR_TRACKING, '2024-07-09T12:00:03.000Z'),
        ])

        const collector = new ItemCollector('session-id', dayjs.utc('2024-07-09T12:00:06.000Z'))
        collector.addCategory(ItemCategory.ERROR_TRACKING, renderer, loader)

        await collector.loadBefore(2)
        await collector.loadBefore(2)

        const secondBeforeCursor = (loader.loadBefore as jest.Mock).mock.calls[1][0]
        expect(secondBeforeCursor.toISOString()).toBe('2024-07-09T12:00:03.001Z')
        expect(
            collector
                .collectItems()
                .map((item) => item.id)
                .sort()
        ).toEqual(['newest', 'same-ts-a', 'same-ts-b'])
    })

    it('keeps after pagination overlapping equal timestamps by 1 ms', async () => {
        const loader = createInMemoryLoader([
            createItem('oldest', ItemCategory.ERROR_TRACKING, '2024-07-09T12:00:01.000Z'),
            createItem('same-ts-a', ItemCategory.ERROR_TRACKING, '2024-07-09T12:00:03.000Z'),
            createItem('same-ts-b', ItemCategory.ERROR_TRACKING, '2024-07-09T12:00:03.000Z'),
        ])

        const collector = new ItemCollector('session-id', dayjs.utc('2024-07-09T12:00:00.000Z'))
        collector.addCategory(ItemCategory.ERROR_TRACKING, renderer, loader)

        await collector.loadAfter(2)
        await collector.loadAfter(2)

        const secondAfterCursor = (loader.loadAfter as jest.Mock).mock.calls[1][0]
        expect(secondAfterCursor.toISOString()).toBe('2024-07-09T12:00:02.999Z')
        expect(
            collector
                .collectItems()
                .map((item) => item.id)
                .sort()
        ).toEqual(['oldest', 'same-ts-a', 'same-ts-b'])
    })
})
