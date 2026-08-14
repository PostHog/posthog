import { act, renderHook } from '@testing-library/react'

import { useCrossSectionDrag } from './useCrossSectionDrag'

describe('useCrossSectionDrag', () => {
    it('inserts a dragged section after a target section', () => {
        const onSectionDrop = jest.fn()
        const { result } = renderHook(() =>
            useCrossSectionDrag({
                sections: [
                    { key: 'first', group: null, isNamed: false, tiles: [] },
                    { key: 'second', group: null, isNamed: false, tiles: [] },
                ],
                disabled: false,
                onTileDrop: jest.fn(),
                onSectionDrop,
            })
        )
        const first = document.createElement('section')
        const second = document.createElement('section')
        first.getBoundingClientRect = () => ({ top: 0, bottom: 100, height: 100 }) as DOMRect
        second.getBoundingClientRect = () => ({ top: 120, bottom: 720, height: 600 }) as DOMRect

        act(() => {
            result.current.registerSection('first', first)
            result.current.registerSection('second', second)
            result.current.startSectionDrag('first', new MouseEvent('pointerdown', { clientY: 20 }) as PointerEvent, 44)
        })

        act(() => {
            window.dispatchEvent(new MouseEvent('pointerup', { clientY: 180 }))
        })

        expect(onSectionDrop).toHaveBeenCalledWith('first', 2)
    })

    it('inserts a dragged section before a target section when moving upward', () => {
        const onSectionDrop = jest.fn()
        const { result } = renderHook(() =>
            useCrossSectionDrag({
                sections: [
                    { key: 'first', group: null, isNamed: false, tiles: [] },
                    { key: 'second', group: null, isNamed: false, tiles: [] },
                ],
                disabled: false,
                onTileDrop: jest.fn(),
                onSectionDrop,
            })
        )
        const first = document.createElement('section')
        const second = document.createElement('section')
        first.getBoundingClientRect = () => ({ top: 0, bottom: 100, height: 100 }) as DOMRect
        second.getBoundingClientRect = () => ({ top: 120, bottom: 220, height: 100 }) as DOMRect

        act(() => {
            result.current.registerSection('first', first)
            result.current.registerSection('second', second)
            result.current.startSectionDrag(
                'second',
                new MouseEvent('pointerdown', { clientY: 180 }) as PointerEvent,
                44
            )
            window.dispatchEvent(new MouseEvent('pointerup', { clientY: 50 }))
        })

        expect(onSectionDrop).toHaveBeenCalledWith('second', 0)
    })

    it('uses a section edge as an ungrouped tile drop zone', () => {
        const onTileDrop = jest.fn()
        const { result } = renderHook(() =>
            useCrossSectionDrag({
                sections: [
                    { key: 'first', group: null, isNamed: false, tiles: [] },
                    { key: 'second', group: null, isNamed: false, tiles: [] },
                ],
                disabled: false,
                onTileDrop,
                onSectionDrop: jest.fn(),
            })
        )
        const first = document.createElement('section')
        const second = document.createElement('section')
        first.getBoundingClientRect = () => ({ top: 0, bottom: 100, height: 100 }) as DOMRect
        second.getBoundingClientRect = () => ({ top: 120, bottom: 220, height: 100 }) as DOMRect

        act(() => {
            result.current.registerSection('first', first)
            result.current.registerSection('second', second)
            result.current.startTileDrag(1, 'first')
            result.current.finishDrag(new MouseEvent('mouseup', { clientY: 95 }))
        })

        expect(onTileDrop).toHaveBeenCalledWith(1, { type: 'gap', position: 1 }, expect.any(MouseEvent), null, null)
    })

    it('uses the top of a tall section as a tile drop zone', () => {
        const onTileDrop = jest.fn()
        const { result } = renderHook(() =>
            useCrossSectionDrag({
                sections: [
                    { key: 'first', group: null, isNamed: false, tiles: [] },
                    { key: 'second', group: null, isNamed: false, tiles: [] },
                ],
                disabled: false,
                onTileDrop,
                onSectionDrop: jest.fn(),
            })
        )
        const first = document.createElement('section')
        const second = document.createElement('section')
        first.getBoundingClientRect = () => ({ top: 0, bottom: 100, height: 100 }) as DOMRect
        second.getBoundingClientRect = () => ({ top: 120, bottom: 720, height: 600 }) as DOMRect

        act(() => {
            result.current.registerSection('first', first)
            result.current.registerSection('second', second)
            result.current.startTileDrag(1, 'first')
            result.current.finishDrag(new MouseEvent('mouseup', { clientY: 180 }))
        })

        expect(onTileDrop).toHaveBeenCalledWith(1, { type: 'gap', position: 1 }, expect.any(MouseEvent), null, null)
    })

    it('uses most of an empty section as a tile drop zone', () => {
        const onTileDrop = jest.fn()
        const { result } = renderHook(() =>
            useCrossSectionDrag({
                sections: [
                    { key: 'first', group: null, isNamed: false, tiles: [] },
                    { key: 'second', group: null, isNamed: false, tiles: [] },
                ],
                disabled: false,
                onTileDrop,
                onSectionDrop: jest.fn(),
            })
        )
        const first = document.createElement('section')
        const second = document.createElement('section')
        first.getBoundingClientRect = () => ({ top: 0, bottom: 100, height: 100 }) as DOMRect
        second.getBoundingClientRect = () => ({ top: 120, bottom: 220, height: 100 }) as DOMRect

        act(() => {
            result.current.registerSection('first', first)
            result.current.registerSection('second', second)
            result.current.startTileDrag(1, 'first')
            result.current.finishDrag(new MouseEvent('mouseup', { clientY: 190 }))
        })

        expect(onTileDrop).toHaveBeenCalledWith(
            1,
            { type: 'section', sectionKey: 'second', position: 1, after: true },
            expect.any(MouseEvent),
            null,
            expect.any(Object)
        )
    })
})
