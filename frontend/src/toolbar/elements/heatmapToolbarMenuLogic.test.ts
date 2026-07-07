import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ElementsEventType } from '~/toolbar/types'

import {
    buildElementStatsProperties,
    computeAreaCandidates,
    dedupeByChainIdentity,
    heatmapToolbarMenuLogic,
    isInFixedContainer,
    resolveAreaElement,
    resolveAreaTarget,
    stepAreaCandidate,
} from './heatmapToolbarMenuLogic'

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

    describe('buildElementStatsProperties', () => {
        it.each([
            [
                'an exact url filter when the wildcard href matches the href',
                'https://example.com/page',
                'https://example.com/page',
                null,
                [{ key: '$current_url', value: 'https://example.com/page', operator: 'exact', type: 'event' }],
            ],
            [
                'a regex url filter when the wildcard href differs',
                'https://example.com/page/1',
                'https://example.com/page/*',
                null,
                [
                    {
                        key: '$current_url',
                        value: '^https\\:\\/\\/example\\.com\\/page\\/.*$',
                        operator: 'regex',
                        type: 'event',
                    },
                ],
            ],
            [
                'an element selector filter when an area is chosen',
                'https://example.com/page',
                'https://example.com/page',
                'nav#main-nav',
                [
                    { key: '$current_url', value: 'https://example.com/page', operator: 'exact', type: 'event' },
                    { key: 'selector', value: 'nav#main-nav', operator: 'exact', type: 'element' },
                ],
            ],
        ])('builds %s', (_name, href, wildcardHref, areaSelector, expected) => {
            expect(buildElementStatsProperties(href, wildcardHref, areaSelector)).toEqual(expected)
        })
    })

    describe('resolveAreaTarget', () => {
        afterEach(() => {
            document.body.innerHTML = ''
        })

        it.each([
            ['snaps to the nearest semantic container', '<nav id="n"><ul><li id="leaf">x</li></ul></nav>', 'leaf', 'n'],
            ['keeps a semantic container that is hovered directly', '<main id="m">x</main>', 'm', 'm'],
            ['falls back to the hovered element when no container wraps it', '<div><b id="b">x</b></div>', 'b', 'b'],
            [
                'snaps to a role-annotated container',
                '<div role="navigation" id="r"><span id="s">x</span></div>',
                's',
                'r',
            ],
        ])('%s', (_name, html, hoveredId, expectedId) => {
            document.body.innerHTML = html
            const hovered = document.getElementById(hoveredId) as HTMLElement
            expect(resolveAreaTarget(hovered).id).toBe(expectedId)
        })
    })

    describe('resolveAreaElement', () => {
        afterEach(() => {
            document.body.innerHTML = ''
        })

        it.each([
            [
                'keeps the tracked element while it is connected',
                (element: HTMLElement) => ({ element, selector: 'nav#other' }),
                'tracked',
            ],
            [
                'follows a replaced node via the stored selector',
                (element: HTMLElement) => {
                    element.remove()
                    return { element, selector: 'nav#other' }
                },
                'replacement',
            ],
            [
                'returns null when the node is gone and the selector matches nothing',
                (element: HTMLElement) => {
                    element.remove()
                    return { element, selector: 'nav#gone' }
                },
                null,
            ],
            [
                'returns null when the node is gone and no selector was derived',
                (element: HTMLElement) => {
                    element.remove()
                    return { element, selector: null }
                },
                null,
            ],
            [
                'returns null when the node is gone and the selector is not valid querySelector input',
                (element: HTMLElement) => {
                    element.remove()
                    return { element, selector: ':::' }
                },
                null,
            ],
        ])('%s', (_name, buildFilter, expectedTestId) => {
            document.body.innerHTML =
                '<nav id="tracked" data-testid="tracked"></nav><nav id="other" data-testid="replacement"></nav>'
            const tracked = document.getElementById('tracked') as HTMLElement
            const filter = buildFilter(tracked)

            const resolved = resolveAreaElement(filter)

            expect(resolved?.dataset.testid ?? null).toBe(expectedTestId)
        })
    })

    describe('stepAreaCandidate', () => {
        afterEach(() => {
            document.body.innerHTML = ''
        })

        function chain(rects: number[]): HTMLElement[] {
            // builds body > el0 > el1 > ... where each element's mocked rect width is
            // rects[i] (same-width neighbours simulate zero-layout wrapper divs)
            const elements: HTMLElement[] = []
            let parent: HTMLElement = document.body
            rects.forEach((width, i) => {
                const el = document.createElement('div')
                el.id = `el${i}`
                el.getBoundingClientRect = () =>
                    ({ top: 0, left: 0, width, height: 100, right: width, bottom: 100 }) as DOMRect
                parent.appendChild(el)
                elements.push(el)
                parent = el
            })
            return elements
        }

        it.each([
            ['up steps to the parent when it is bigger', [300, 200, 100], 2, 2, 'up', 1],
            ['up skips same-size wrapper parents', [300, 200, 200, 200, 100], 4, 3, 'up', 0],
            ['up stops below body when nothing bigger remains', [300], 0, 0, 'up', 0],
            ['down steps back toward the anchor', [300, 200, 100], 2, 0, 'down', 1],
            ['down skips same-size wrappers next to the candidate', [300, 300, 300, 100], 3, 0, 'down', 3],
            ['down at the anchor stays put', [300, 200, 100], 2, 2, 'down', 2],
        ] as const)('%s', (_name, rects, anchorIdx, candidateIdx, direction, expectedIdx) => {
            const els = chain([...rects])
            expect(stepAreaCandidate(els[anchorIdx], els[candidateIdx], direction)).toBe(els[expectedIdx])
        })
    })

    describe('computeAreaCandidates', () => {
        afterEach(() => {
            document.body.innerHTML = ''
        })

        function addElement(
            tag: string,
            rect: { top: number; left: number; width: number; height: number },
            parent: HTMLElement = document.body
        ): HTMLElement {
            const el = document.createElement(tag)
            el.getBoundingClientRect = () =>
                ({ ...rect, right: rect.left + rect.width, bottom: rect.top + rect.height }) as DOMRect
            parent.appendChild(el)
            return el
        }

        it('offers visible containers sorted biggest first, dropping too-small elements and non-containers', () => {
            const big = addElement('div', { top: 0, left: 0, width: 800, height: 600 })
            const nav = addElement('nav', { top: 0, left: 0, width: 200, height: 600 })
            addElement('div', { top: 0, left: 0, width: 50, height: 20 }) // below the size floor
            addElement('span', { top: 0, left: 0, width: 400, height: 400 }) // not a container tag

            expect(computeAreaCandidates()).toEqual([big, nav])
        })

        it('collapses a same-rect wrapper chain to its deepest element', () => {
            const outer = addElement('div', { top: 0, left: 0, width: 800, height: 600 })
            const inner = addElement('div', { top: 0, left: 0, width: 800, height: 600 }, outer)
            const distinct = addElement('div', { top: 0, left: 0, width: 400, height: 300 }, inner)

            expect(computeAreaCandidates()).toEqual([inner, distinct])
        })
    })

    describe('isInFixedContainer', () => {
        afterEach(() => {
            document.body.innerHTML = ''
        })

        it.each([
            ['a fixed element itself', 'fixed', 'self', true],
            ['a sticky element itself', 'sticky', 'self', true],
            ['a child of a fixed container', 'fixed', 'child', true],
            ['a static element', 'static', 'self', false],
        ])('detects %s', (_name, position, which, expected) => {
            const container = document.createElement('div')
            container.style.position = position
            const child = document.createElement('span')
            container.appendChild(child)
            document.body.appendChild(container)
            expect(isInFixedContainer(which === 'self' ? container : child)).toBe(expected)
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

        it('reloads the clickmap with the element selector filter when an area is chosen', async () => {
            await expectLogic(logic, () => logic.actions.enableHeatmap()).toDispatchActions(['getElementStatsSuccess'])

            const area = document.createElement('nav')
            area.id = 'main-nav'
            document.body.appendChild(area)
            try {
                await expectLogic(logic, () => logic.actions.selectHeatmapAreaFilter(area)).toDispatchActions([
                    'setHeatmapAreaFilter',
                    'getElementStatsSuccess',
                ])

                const lastCall = (toolbarApi.elementStats.list as jest.Mock).mock.calls.at(-1)[0]
                expect(lastCall.properties).toContainEqual(
                    expect.objectContaining({
                        key: 'selector',
                        type: 'element',
                        value: expect.stringContaining('nav'),
                    })
                )

                await expectLogic(logic, () => logic.actions.selectHeatmapAreaFilter(null)).toDispatchActions([
                    'getElementStatsSuccess',
                ])
                const clearedCall = (toolbarApi.elementStats.list as jest.Mock).mock.calls.at(-1)[0]
                expect(clearedCall.properties).toHaveLength(1)
            } finally {
                area.remove()
            }
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
