import { fireEvent, renderHook } from '@testing-library/react'

import { useMousePosition } from './useMousePosition'

const CONTAINER_LEFT = 100
const CONTAINER_TOP = 50
const CONTAINER_WIDTH = 200
const CONTAINER_HEIGHT = 300

function createContainer(): HTMLElement {
    const element = document.createElement('div')
    element.getBoundingClientRect = () =>
        ({
            left: CONTAINER_LEFT,
            top: CONTAINER_TOP,
            width: CONTAINER_WIDTH,
            height: CONTAINER_HEIGHT,
        }) as DOMRect
    return element
}

describe('useMousePosition', () => {
    test.each<[string, number, number]>([
        ['left of', 90, 100],
        ['above', 150, 40],
        ['right of', 310, 100],
        ['below', 150, 360],
    ])('clears the container position once the pointer is %s the container', (_, clientX, clientY) => {
        const container = createContainer()
        const { result } = renderHook(() => useMousePosition(container))

        fireEvent.mouseMove(window, { clientX: 150, clientY: 100 })
        expect(result.current).toEqual({ x: 50, y: 50 })

        fireEvent.mouseMove(window, { clientX, clientY })
        expect(result.current).toBeNull()
    })

    it('reports viewport positions when no container is given', () => {
        const { result } = renderHook(() => useMousePosition())

        expect(result.current).toBeNull()

        fireEvent.mouseMove(window, { clientX: 150, clientY: 100 })

        expect(result.current).toEqual({ x: 150, y: 100 })
    })
})
