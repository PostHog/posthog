import { fireEvent, render } from '@testing-library/react'

import { TreeRowOverflowText } from './TreeRowOverflowText'

describe('TreeRowOverflowText', () => {
    const OVERFLOW_PX = 80

    beforeEach(() => {
        // jsdom has no layout, so make the name look 80px wider than the space it has
        jest.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(200)
        jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(200 - OVERFLOW_PX)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    function renderRow(): { row: HTMLElement; name: HTMLElement } {
        const { container } = render(
            <div role="treeitem" tabIndex={0}>
                <span>icon</span>
                <TreeRowOverflowText>a_very_long_view_name</TreeRowOverflowText>
            </div>
        )
        return {
            row: container.querySelector('[role="treeitem"]') as HTMLElement,
            name: container.querySelector('.inline-block') as HTMLElement,
        }
    }

    it('slides the name when the pointer enters the row, not only the name, and puts it back on leave', () => {
        const { row, name } = renderRow()
        expect(name.style.transform).toEqual('translateX(0)')

        fireEvent.pointerEnter(row)
        expect(name.style.transform).toEqual(`translateX(-${OVERFLOW_PX}px)`)

        fireEvent.pointerLeave(row)
        expect(name.style.transform).toEqual('translateX(0)')
    })
})
