import { fireEvent, render, waitFor } from '@testing-library/react'

import { Dayjs, dayjs } from 'lib/dayjs'

import { SessionTimeline } from './SessionTimeline'
import { ItemCategory, ItemCollector, ItemLoader, ItemRenderer, TimelineItem } from './timeline'

interface TestItem extends TimelineItem {
    payload: { label: string }
}

function buildRenderer(category: ItemCategory): ItemRenderer<TestItem> {
    return {
        sourceIcon: () => <span>{category}</span>,
        categoryIcon: <span>{category}</span>,
        render: ({ item }) => <span className="truncate text-xs">{item.payload.label}</span>,
    }
}

function generateItems(category: ItemCategory, center: Dayjs, countBefore: number, countAfter: number): TestItem[] {
    const items: TestItem[] = []

    for (let i = countBefore; i >= 1; i--) {
        items.push({
            id: `${category}-before-${i}`,
            category,
            timestamp: center.subtract(i, 'second'),
            payload: { label: `${category} before ${i}` },
        })
    }

    for (let i = 1; i <= countAfter; i++) {
        items.push({
            id: `${category}-after-${i}`,
            category,
            timestamp: center.add(i, 'second'),
            payload: { label: `${category} after ${i}` },
        })
    }

    return items.sort((a, b) => a.timestamp.diff(b.timestamp))
}

class TestPagedLoader implements ItemLoader<TestItem> {
    readonly loadBefore = jest.fn(async (cursor: Dayjs, limit: number) => {
        const before = this.items.filter((item) => item.timestamp.isBefore(cursor))
        return {
            items: before.slice(-limit),
            hasMoreBefore: before.length > limit,
        }
    })

    readonly loadAfter = jest.fn(async (cursor: Dayjs, limit: number) => {
        const after = this.items.filter((item) => item.timestamp.isAfter(cursor))
        return {
            items: after.slice(0, limit),
            hasMoreAfter: after.length > limit,
        }
    })

    constructor(private readonly items: TestItem[]) {}
}

async function waitForCallCountToSettle(getCallCount: () => number): Promise<number> {
    let previousCallCount = getCallCount()
    let stableChecks = 0

    while (stableChecks < 5) {
        await new Promise((resolve) => setTimeout(resolve, 20))

        const nextCallCount = getCallCount()
        if (nextCallCount === previousCallCount) {
            stableChecks += 1
        } else {
            stableChecks = 0
            previousCallCount = nextCallCount
        }
    }

    return previousCallCount
}

describe('SessionTimeline', () => {
    it('refills items when category filtering leaves the viewport underfilled', async () => {
        const center = dayjs.utc('2024-07-09T12:00:00.000Z')
        const collector = new ItemCollector('session-id', center)

        const categoriesToLoad: ItemCategory[] = [
            ItemCategory.ERROR_TRACKING,
            ItemCategory.PAGE_VIEWS,
            ItemCategory.CUSTOM_EVENTS,
            ItemCategory.CONSOLE_LOGS,
        ]

        const loaders = new Map<ItemCategory, TestPagedLoader>()

        categoriesToLoad.forEach((category) => {
            const loader = new TestPagedLoader(generateItems(category, center, 100, 100))
            loaders.set(category, loader)
            collector.addCategory(category, buildRenderer(category), loader)
        })

        const { container } = render(
            <div style={{ width: 700, height: 320 }}>
                <SessionTimeline collector={collector} />
            </div>
        )

        const scrollContainer = container.querySelector(
            '[data-attr="session-timeline-scroll-container"]'
        ) as HTMLDivElement
        expect(scrollContainer).toBeTruthy()

        Object.defineProperty(scrollContainer, 'clientHeight', {
            configurable: true,
            get: () => 320,
        })

        Object.defineProperty(scrollContainer, 'scrollHeight', {
            configurable: true,
            get: () => scrollContainer.querySelectorAll('[data-item-id]').length * 32,
        })

        await waitFor(() => {
            const rowCount = scrollContainer.querySelectorAll('[data-item-id]').length
            if (rowCount <= 0) {
                throw new Error('Timeline did not render any items yet')
            }
        })

        const errorLoader = loaders.get(ItemCategory.ERROR_TRACKING)
        expect(errorLoader).toBeTruthy()
        const beforeToggleCalls =
            (errorLoader?.loadBefore.mock.calls.length ?? 0) + (errorLoader?.loadAfter.mock.calls.length ?? 0)

        const pageViewsToggle = container.querySelector(
            '[data-attr="session-timeline-category-toggle-pageviews"]'
        ) as HTMLButtonElement
        const customEventsToggle = container.querySelector(
            '[data-attr="session-timeline-category-toggle-custom-events"]'
        ) as HTMLButtonElement
        const consoleLogsToggle = container.querySelector(
            '[data-attr="session-timeline-category-toggle-console-logs"]'
        ) as HTMLButtonElement

        fireEvent.click(pageViewsToggle)
        fireEvent.click(customEventsToggle)
        fireEvent.click(consoleLogsToggle)

        await waitFor(() => {
            const afterToggleCalls =
                (errorLoader?.loadBefore.mock.calls.length ?? 0) + (errorLoader?.loadAfter.mock.calls.length ?? 0)
            if (afterToggleCalls <= beforeToggleCalls) {
                throw new Error('Expected selected category loader to fetch additional data after filtering')
            }
        })
    })

    it('stops filter refill when only hidden categories keep growing', async () => {
        const center = dayjs.utc('2024-07-09T12:00:00.000Z')
        const collector = new ItemCollector('session-id', center)

        const visibleLoader = new TestPagedLoader(generateItems(ItemCategory.ERROR_TRACKING, center, 2, 2))
        const hiddenLoader = new TestPagedLoader(generateItems(ItemCategory.PAGE_VIEWS, center, 2000, 2000))

        collector.addCategory(ItemCategory.ERROR_TRACKING, buildRenderer(ItemCategory.ERROR_TRACKING), visibleLoader)
        collector.addCategory(ItemCategory.PAGE_VIEWS, buildRenderer(ItemCategory.PAGE_VIEWS), hiddenLoader)

        const { container } = render(
            <div style={{ width: 700, height: 320 }}>
                <SessionTimeline collector={collector} />
            </div>
        )

        const scrollContainer = container.querySelector(
            '[data-attr="session-timeline-scroll-container"]'
        ) as HTMLDivElement
        expect(scrollContainer).toBeTruthy()

        Object.defineProperty(scrollContainer, 'clientHeight', {
            configurable: true,
            get: () => 320,
        })

        Object.defineProperty(scrollContainer, 'scrollHeight', {
            configurable: true,
            get: () => scrollContainer.querySelectorAll('[data-item-id]').length * 32,
        })

        await waitFor(() => {
            const rowCount = scrollContainer.querySelectorAll('[data-item-id]').length
            if (rowCount <= 0) {
                throw new Error('Timeline did not render any items yet')
            }
        })

        const hiddenCallsBeforeToggle = await waitForCallCountToSettle(
            () => hiddenLoader.loadBefore.mock.calls.length + hiddenLoader.loadAfter.mock.calls.length
        )

        const pageViewsToggle = container.querySelector(
            '[data-attr="session-timeline-category-toggle-pageviews"]'
        ) as HTMLButtonElement
        fireEvent.click(pageViewsToggle)

        await waitFor(() => {
            const hiddenCallsAfterToggle =
                hiddenLoader.loadBefore.mock.calls.length + hiddenLoader.loadAfter.mock.calls.length
            if (hiddenCallsAfterToggle <= hiddenCallsBeforeToggle) {
                throw new Error('Expected hidden loader to be queried at least once after filtering')
            }
        })

        const settledHiddenCallCount = await waitForCallCountToSettle(
            () => hiddenLoader.loadBefore.mock.calls.length + hiddenLoader.loadAfter.mock.calls.length
        )

        expect(settledHiddenCallCount - hiddenCallsBeforeToggle).toBeLessThanOrEqual(2)
    })
})
