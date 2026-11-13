import { useCallback, useEffect, useRef } from 'react'
import type { MutableRefObject, RefObject } from 'react'

import { type TileCarry, type TilePickUp, carryTile, getTilePickUp, travelledLikeClick } from './carryTile'

export type TileCarryInput = 'drag' | 'click' | 'canceled'
export type TileCarryKind = 'move' | 'resize'

interface UseCarryTileProps {
    containerRef: RefObject<HTMLElement>
    enabled: boolean
    handleSelector: string
    cancelSelector: string
    onCarryingChange: (carrying: TileCarryKind | null) => void
    /** Runs before the grid receives the release that ends a canceled gesture. */
    onCarryCanceled?: (kind: TileCarryKind) => void
}

export interface CarryTileControls {
    tileCarryInputRef: MutableRefObject<TileCarryInput>
    carryHeld: (target: HTMLElement | null, kind: TileCarryKind) => void
}

export function useCarryTile({
    containerRef,
    enabled,
    handleSelector,
    cancelSelector,
    onCarryingChange,
    onCarryCanceled,
}: UseCarryTileProps): CarryTileControls {
    const tileCarryInputRef = useRef<TileCarryInput>('drag')
    const carryRef = useRef<TileCarry | null>(null)
    const pressRef = useRef<{ x: number; y: number } | null>(null)
    const onCarryingChangeRef = useRef(onCarryingChange)
    onCarryingChangeRef.current = onCarryingChange
    const onCarryCanceledRef = useRef(onCarryCanceled)
    onCarryCanceledRef.current = onCarryCanceled

    const startCarrying = useCallback(
        (
            pickUp: TilePickUp,
            clientX: number,
            clientY: number,
            initialInput: 'drag' | 'click',
            kind: TileCarryKind
        ): void => {
            let input = initialInput
            // Setting the state re-renders every subscriber, so a held drag only sets it once its button is released.
            let announced = false
            const announce = (): void => {
                announced = true
                onCarryingChangeRef.current(kind)
            }
            const finish = (finalInput: TileCarryInput): void => {
                carryRef.current = null
                if (announced) {
                    onCarryingChangeRef.current(null)
                }
                tileCarryInputRef.current = finalInput
                // The drag stop handler reads the input once the release reaches react-grid-layout, after this handler.
                window.setTimeout(() => {
                    tileCarryInputRef.current = 'drag'
                }, 0)
            }
            tileCarryInputRef.current = input
            if (input === 'click') {
                announce()
            }
            carryRef.current = carryTile({
                ...pickUp,
                clientX,
                clientY,
                held: input === 'drag',
                onHeldRelease: (event) => {
                    // A resize starts on the press, so a press released in place is a click on the resize handle.
                    if (
                        kind === 'resize' &&
                        travelledLikeClick({ x: clientX, y: clientY }, event.clientX, event.clientY)
                    ) {
                        input = 'click'
                        tileCarryInputRef.current = input
                    }
                    announce()
                },
                onDrop: () => finish(input),
                onCancel: () => {
                    onCarryCanceledRef.current?.(kind)
                    finish('canceled')
                },
            })
        },
        []
    )

    const carryHeld = useCallback(
        (target: HTMLElement | null, kind: TileCarryKind): void => {
            const press = pressRef.current
            const grid = target?.closest('.react-grid-item')?.parentElement
            if (carryRef.current || !press || !target || !grid) {
                return
            }
            startCarrying({ target, grid }, press.x, press.y, 'drag', kind)
        },
        [startCarrying]
    )

    useEffect(() => {
        const container = containerRef.current
        if (!enabled || !container) {
            return
        }

        const onMouseDown = (event: MouseEvent): void => {
            pressRef.current = event.button === 0 ? { x: event.clientX, y: event.clientY } : null
        }

        const onClick = (event: MouseEvent): void => {
            if (carryRef.current) {
                return
            }
            const pickUp = getTilePickUp(event, pressRef.current, handleSelector, cancelSelector)
            if (!pickUp) {
                return
            }
            event.preventDefault()
            event.stopPropagation()
            startCarrying(pickUp, event.clientX, event.clientY, 'click', 'move')
        }

        container.addEventListener('mousedown', onMouseDown, { capture: true })
        container.addEventListener('click', onClick, { capture: true })
        return () => {
            container.removeEventListener('mousedown', onMouseDown, { capture: true })
            container.removeEventListener('click', onClick, { capture: true })
            carryRef.current?.cancel()
        }
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- containerRef is a stable ref object
    }, [enabled, handleSelector, cancelSelector, startCarrying])

    return { tileCarryInputRef, carryHeld }
}
