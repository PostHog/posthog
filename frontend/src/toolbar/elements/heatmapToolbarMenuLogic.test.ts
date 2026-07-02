import { ElementsEventType } from '~/toolbar/types'

import { dedupeByChainIdentity } from './heatmapToolbarMenuLogic'

function statsRow(overrides: Partial<ElementsEventType>): ElementsEventType {
    return {
        count: 1,
        hash: null,
        type: '$autocapture',
        elements: [{ tag_name: 'button', attr_class: ['btn'], nth_child: 1, nth_of_type: 1, attributes: {} }],
        ...overrides,
    } as ElementsEventType
}

describe('dedupeByChainIdentity', () => {
    const cases = [
        {
            name: 'keeps distinct chains even though the API returns hash null for every row',
            events: [
                statsRow({ elements: [{ tag_name: 'button', attributes: {} }] as ElementsEventType['elements'] }),
                statsRow({ elements: [{ tag_name: 'a', attributes: {} }] as ElementsEventType['elements'] }),
            ],
            expectedCount: 2,
        },
        {
            name: 'drops a chain repeated across paginated pages, keeping the first occurrence',
            events: [statsRow({ count: 10 }), statsRow({ count: 3 })],
            expectedCount: 1,
        },
        {
            name: 'keeps identical chains that differ by event type',
            events: [statsRow({ type: '$autocapture' }), statsRow({ type: '$rageclick' })],
            expectedCount: 2,
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
