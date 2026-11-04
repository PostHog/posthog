import { displayOptionPages } from './displayOptionPages'
import type { DisplayOptionName, DisplayOptionTab } from './displayOptions'

const item = (
    name: DisplayOptionName,
    { changed = 0, advanced = false } = {}
): DisplayOptionTab['sections'][number]['items'][number] => ({
    name,
    element: null,
    changed,
    advanced,
})

describe('displayOptionPages', () => {
    it('keeps common options on the list and puts the rest one step away', () => {
        const tabs: DisplayOptionTab[] = [
            {
                key: 'general',
                label: 'General',
                count: 2,
                sections: [
                    {
                        key: 'display',
                        group: 'display',
                        items: [item('legend', { changed: 1 }), item('annotations', { changed: 1, advanced: true })],
                    },
                ],
            },
            {
                key: 'axes',
                label: 'Axes',
                count: 1,
                sections: [
                    { key: 'x-axis', group: 'x-axis', title: 'X-axis', items: [item('xAxisLabel')] },
                    { key: 'y-axis', group: 'y-axis', title: 'Y-axis', items: [item('yAxisLabel', { changed: 1 })] },
                ],
            },
            {
                key: 'lines',
                label: 'Lines',
                count: 0,
                sections: [
                    { key: 'style', group: 'style', title: 'Style', items: [item('lineStyle')] },
                    { key: 'overlays', group: 'overlays', title: 'Overlays', items: [item('trendLines')] },
                ],
            },
        ]

        const { home, pages } = displayOptionPages(tabs)

        expect(home.flatMap((section) => section.items.map((option) => option.name))).toEqual(['legend'])
        expect(pages.map(({ key, title, count }) => ({ key, title, count }))).toEqual([
            { key: 'x-axis', title: 'X-axis', count: 0 },
            { key: 'y-axis', title: 'Y-axis', count: 1 },
            { key: 'lines', title: 'Lines', count: 0 },
            { key: 'more', title: 'More options', count: 1 },
        ])
        expect(pages[1].sections[0].title).toBeUndefined()
        expect(pages[2].sections.map((section) => section.title)).toEqual(['Style', 'Overlays'])
    })
})
