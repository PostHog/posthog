import { renderHook, act } from '@testing-library/react'
import { useDragAndSnap } from './useDragAndSnap'

describe('useDragAndSnap', () => {
    let mockOnPositionChange: jest.Mock

    beforeEach(() => {
        mockOnPositionChange = jest.fn()

        // Mock addEventListener and removeEventListener
        jest.spyOn(document, 'addEventListener')
        jest.spyOn(document, 'removeEventListener')
    })

    it('should initialize with default values', () => {
        const { result } = renderHook(() => useDragAndSnap({ onPositionChange: mockOnPositionChange }))

        expect(result.current.isDragging).toBe(false)
        expect(result.current.isAnimating).toBe(false)
        expect(result.current.hasDragged).toBe(false)
        expect(result.current.containerStyle).toEqual({})
        expect(result.current.dragElementRef.current).toBeNull()
    })

    it('should not start drag when disabled', () => {
        const { result } = renderHook(() =>
            useDragAndSnap({
                onPositionChange: mockOnPositionChange,
                disabled: true,
            })
        )

        const mockEvent = {
            button: 0,
            clientX: 200,
            clientY: 200,
            preventDefault: jest.fn(),
        } as any

        act(() => {
            result.current.handleMouseDown(mockEvent)
        })

        expect(result.current.isDragging).toBe(false)
    })

    it('should not start drag on non-left mouse button', () => {
        const { result } = renderHook(() => useDragAndSnap({ onPositionChange: mockOnPositionChange }))

        const mockEvent = {
            button: 1, // right click
            clientX: 200,
            clientY: 200,
            preventDefault: jest.fn(),
        } as any

        act(() => {
            result.current.handleMouseDown(mockEvent)
        })

        expect(result.current.isDragging).toBe(false)
    })

    it('should start drag on valid mouse down', () => {
        const { result } = renderHook(() => useDragAndSnap({ onPositionChange: mockOnPositionChange }))

        // Mock dragElementRef
        const mockElement = {
            getBoundingClientRect: () => ({ left: 100, top: 100, width: 48, height: 48 }),
        }
        // @ts-expect-error - Mocking ref for testing
        result.current.dragElementRef.current = mockElement as any

        const mockEvent = {
            button: 0,
            clientX: 120,
            clientY: 120,
            preventDefault: jest.fn(),
        } as any

        act(() => {
            result.current.handleMouseDown(mockEvent)
        })

        expect(mockEvent.preventDefault).toHaveBeenCalled()
        expect(document.addEventListener).toHaveBeenCalledWith('mousemove', expect.any(Function))
        expect(document.addEventListener).toHaveBeenCalledWith('mouseup', expect.any(Function))
    })

    it('should not start drag on touch devices with small screens', () => {
        // Mock touch device
        Object.defineProperty(window, 'ontouchstart', { value: true, writable: true })
        Object.defineProperty(window, 'innerWidth', { value: 500, writable: true }) // < 640

        const { result } = renderHook(() => useDragAndSnap({ onPositionChange: mockOnPositionChange }))

        const mockElement = {
            getBoundingClientRect: () => ({ left: 100, top: 100, width: 48, height: 48 }),
        }
        // @ts-expect-error - Mocking ref for testing
        result.current.dragElementRef.current = mockElement as any

        const mockEvent = {
            button: 0,
            clientX: 120,
            clientY: 120,
            preventDefault: jest.fn(),
        } as any

        act(() => {
            result.current.handleMouseDown(mockEvent)
        })

        expect(document.addEventListener).not.toHaveBeenCalled()
    })

    it('should apply correct container styles during initial mouse down', () => {
        const { result } = renderHook(() => useDragAndSnap({ onPositionChange: mockOnPositionChange }))

        const mockElement = {
            getBoundingClientRect: () => ({ left: 100, top: 100, width: 48, height: 48 }),
        }
        // @ts-expect-error - Mocking ref for testing
        result.current.dragElementRef.current = mockElement as any

        const mockEvent = {
            button: 0,
            clientX: 120,
            clientY: 120,
            preventDefault: jest.fn(),
        } as any

        act(() => {
            result.current.handleMouseDown(mockEvent)
        })

        // Should have initial drag position (but not yet dragging, so no special styles)
        expect(result.current.isDragging).toBe(false)
        expect(result.current.containerStyle).toEqual({})
    })
})
