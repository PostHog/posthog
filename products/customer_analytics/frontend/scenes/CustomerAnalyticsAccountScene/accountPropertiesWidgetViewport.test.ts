import { getVisibleRowsHeight } from './accountPropertiesWidgetViewport'

function buildContent(heights: number[], alertAfterRow?: number): HTMLElement {
    const content = document.createElement('div')
    jest.spyOn(content, 'getBoundingClientRect').mockReturnValue({ top: 100 } as DOMRect)
    let top = 0
    const add = (dataAttr: string | null, height: number): void => {
        const child = document.createElement('div')
        if (dataAttr) {
            child.setAttribute('data-attr', dataAttr)
        }
        // jsdom has no layout, so rows report the geometry a browser would.
        jest.spyOn(child, 'getBoundingClientRect').mockReturnValue({ bottom: 100 + top + height } as DOMRect)
        top += height + 12
        content.appendChild(child)
    }
    heights.forEach((height, index) => {
        add(index % 2 ? 'account-native-property-row' : 'account-property-row', height)
        if (index === alertAfterRow) {
            add(null, 40)
        }
    })
    return content
}

describe('getVisibleRowsHeight', () => {
    it('does not limit ten rows', () => {
        expect(getVisibleRowsHeight(buildContent(Array(10).fill(30)))).toBeNull()
    })

    it.each([
        [30, 80, 30, 30, 120, 30, 30, 30, 30, 50, 30],
        [30.2, 80.3, 30.1, 30, 120.4, 30.2, 30, 30.3, 30, 50.2, 30],
    ])('fully includes the tenth row when the first row height is %s', (...heights) => {
        const tenthBottom = heights.slice(0, 10).reduce((sum, height) => sum + height + 12, 0) - 12
        expect(getVisibleRowsHeight(buildContent(heights))).toBe(Math.ceil(tenthBottom))
    })

    it('does not count alerts as properties', () => {
        expect(getVisibleRowsHeight(buildContent(Array(10).fill(30), 2))).toBeNull()
    })
})
