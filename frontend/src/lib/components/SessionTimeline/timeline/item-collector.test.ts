import { dayjs } from 'lib/dayjs'

import { ItemCategory, ItemCollector, ItemLoader, ItemRenderer, TimelineItem } from '.'

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
})
