import type { ElementStatsApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { buildElementStatsParams, computeClickmapBoxes } from './recordingClickmapLogic'

function statsRow(overrides: Partial<ElementStatsApi>): ElementStatsApi {
    return {
        count: 1,
        hash: null,
        type: '$autocapture',
        elements: [{ tag_name: 'button', attr_id: 'cta', nth_child: 1, nth_of_type: 1, attributes: {} }],
        ...overrides,
    }
}

describe('recordingClickmapLogic', () => {
    describe('buildElementStatsParams', () => {
        it.each([
            {
                name: 'filters stats to the exact page URL',
                href: 'https://example.com/pricing',
                isPattern: false,
                expectedProperty: {
                    key: '$current_url',
                    value: 'https://example.com/pricing',
                    operator: 'exact',
                    type: 'event',
                },
            },
            {
                name: 'converts * wildcards to an anchored regex',
                href: 'https://example.com/blog/*',
                isPattern: true,
                expectedProperty: {
                    key: '$current_url',
                    value: '^https\\:\\/\\/example\\.com\\/blog\\/.*$',
                    operator: 'regex',
                    type: 'event',
                },
            },
        ])('$name', ({ href, isPattern, expectedProperty }) => {
            const params = buildElementStatsParams(href, isPattern, { date_from: '-7d' }, ['data-attr'])
            expect(JSON.parse((params as { properties?: string }).properties ?? '[]')).toEqual([expectedProperty])
        })
    })

    describe('computeClickmapBoxes', () => {
        let snapshotDocument: Document

        beforeEach(() => {
            snapshotDocument = document.implementation.createHTMLDocument()
            snapshotDocument.body.innerHTML = `
                <main>
                    <button id="cta">Sign up</button>
                    <a id="docs-link" href="/docs">Docs</a>
                </main>
            `
            jest.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
                top: 10,
                left: 20,
                width: 100,
                height: 40,
                right: 120,
                bottom: 50,
                x: 20,
                y: 10,
                toJSON: () => ({}),
            })
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('aggregates counts per event type from chains resolving to the same element', () => {
            const boxes = computeClickmapBoxes(
                [
                    statsRow({ count: 10 }),
                    statsRow({ count: 3, hash: 'rage', type: '$rageclick' }),
                    statsRow({ count: 2, hash: 'dead', type: '$dead_click' }),
                ],
                snapshotDocument,
                null,
                ['data-attr']
            )
            expect(boxes).toHaveLength(1)
            expect(boxes[0]).toMatchObject({
                count: 15,
                clickCount: 10,
                rageclickCount: 3,
                deadclickCount: 2,
                label: 'Sign up',
                displaySelector: 'button#cta',
            })
        })

        it('produces one box per matched element, sorted by count descending', () => {
            const boxes = computeClickmapBoxes(
                [
                    statsRow({ count: 2 }),
                    statsRow({
                        count: 9,
                        elements: [
                            {
                                tag_name: 'a',
                                attr_id: 'docs-link',
                                href: '/docs',
                                nth_child: 2,
                                nth_of_type: 1,
                                attributes: {},
                            },
                        ],
                    }),
                ],
                snapshotDocument,
                null,
                ['data-attr']
            )
            expect(boxes.map((box) => box.count)).toEqual([9, 2])
        })

        it('drops chains that match nothing in the snapshot', () => {
            const boxes = computeClickmapBoxes(
                [
                    statsRow({
                        count: 5,
                        elements: [{ tag_name: 'select', attr_id: 'not-in-snapshot', attributes: {} }],
                    }),
                ],
                snapshotDocument,
                null,
                ['data-attr']
            )
            expect(boxes).toHaveLength(0)
        })

        it('offsets boxes by the snapshot scroll position', () => {
            const boxes = computeClickmapBoxes(
                [statsRow({ count: 1 })],
                snapshotDocument,
                { scrollX: 5, scrollY: 200 },
                ['data-attr']
            )
            expect(boxes[0]).toMatchObject({ top: 210, left: 25 })
        })
    })
})
