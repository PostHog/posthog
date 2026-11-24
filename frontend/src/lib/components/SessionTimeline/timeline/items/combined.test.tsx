import { render } from '@testing-library/react'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { ItemCategory } from '..'
import { CombinedEventLoader } from './combined'
import { PageItem, pageRenderer } from './page'

describe('CombinedEventLoader navigation events', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = { current_team: { id: 1 } } as any
    })

    afterEach(() => {
        jest.restoreAllMocks()
        delete window.POSTHOG_APP_CONTEXT
    })

    it.each([
        ['$pageview', undefined, '/checkout', true],
        ['$screen', 'Checkout', 'Checkout', false],
        ['$screen', 'app://checkout/details', 'app://checkout/details', false],
        ['$screen', undefined, 'Unknown screen', false],
    ])(
        'renders %s with screen name %s in the page-view category',
        async (eventName, screenName, label, hasPageLink) => {
            const event: Record<string, unknown> = {
                uuid: 'navigation-event',
                event: eventName,
                timestamp: '2026-01-01T00:00:00.000Z',
                'properties.$lib': eventName === '$screen' ? 'posthog-ios' : 'web',
                'properties.$current_url': 'https://example.com/checkout',
                'properties.$screen_name': screenName,
            }
            const querySpy = jest.spyOn(api, 'query').mockImplementation(async (query: any) => ({
                results: [query.select.map((column: string) => event[column])],
            }))
            const timestamp = dayjs.utc(event.timestamp as string)
            const loader = new CombinedEventLoader('session-id', timestamp)

            for (const direction of ['loadBefore', 'loadAfter'] as const) {
                const { items } = await loader[direction](timestamp, 100)
                expect(querySpy.mock.calls.at(-1)?.[0]).toMatchObject({
                    where: expect.arrayContaining([expect.stringContaining(`equals(event, '${eventName}')`)]),
                })
                expect(items).toHaveLength(1)
                expect(items[0].category).toBe(ItemCategory.PAGE_VIEWS)

                const item = items[0] as PageItem
                const Preview = pageRenderer.render
                const { getByText, unmount } = render(<Preview item={item} />)
                expect(getByText(label)).toBeTruthy()
                expect(pageRenderer.getMenuItems?.({ item })?.some((entry) => entry.key === 'open-page-view')).toBe(
                    hasPageLink
                )
                unmount()
            }
        }
    )
})
