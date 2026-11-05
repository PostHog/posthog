import { useCallback, useEffect, useRef } from 'react'
import type { MutableRefObject, RefObject } from 'react'

import { type TileCarry, type TilePickUp, carryTile, getTilePickUp } from './carryTile'

export type TileMoveInput = 'drag' | 'click' | 'canceled'

interface UseClickToMoveTileProps {
    containerRef: RefObject<HTMLElement>
    enabled: boolean
    handleSelector: string
    cancelSelector: string
    onCarryingChange: (carrying: boolean) => void
}

export interface ClickToMoveTile {
    tileMoveInputRef: MutableRefObject<TileMoveInput>
    carryHeldDrag: (gridItem: HTMLElement | null) => void
}

export function useClickToMoveTile({
    containerRef,
    enabled,
    handleSelector,
    cancelSelector,
    onCarryingChange,
}: UseClickToMoveTileProps): ClickToMoveTile {
    const tileMoveInputRef = useRef<TileMoveInput>('drag')
    const carryRef = useRef<TileCarry | null>(null)
    const pressRef = useRef<{ x: number; y: number } | null>(null)
    const onCarryingChangeRef = useRef(onCarryingChange)
    onCarryingChangeRef.current = onCarryingChange

    const startCarrying = useCallback(
        (pickUp: TilePickUp, clientX: number, clientY: number, input: 'drag' | 'click'): void => {
            // Setting the state re-renders every subscriber, so a held drag only sets it once its button is released.
            let announced = false
            const announce = (): void => {
                announced = true
                onCarryingChangeRef.current(true)
            }
            const finish = (finalInput: TileMoveInput): void => {
                carryRef.current = null
                if (announced) {
                    onCarryingChangeRef.current(false)
                }
                tileMoveInputRef.current = finalInput
                // The drag stop handler reads the input once the release reaches react-grid-layout, after this handler.
                window.setTimeout(() => {
                    tileMoveInputRef.current = 'drag'
                }, 0)
            }
            tileMoveInputRef.current = input
            if (input === 'click') {
                announce()
            }
            carryRef.current = carryTile({
                ...pickUp,
                clientX,
                clientY,
                held: input === 'drag',
                onHeldRelease: announce,
                onDrop: () => finish(input),
                onCancel: () => finish('canceled'),
            })
        },
        []
    )

    const carryHeldDrag = useCallback(
        (gridItem: HTMLElement | null): void => {
            const press = pressRef.current
            const grid = gridItem?.parentElement
            if (carryRef.current || !press || !gridItem || !grid) {
                return
            }
            startCarrying({ target: gridItem, grid }, press.x, press.y, 'drag')
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
            startCarrying(pickUp, event.clientX, event.clientY, 'click')
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

    return { tileMoveInputRef, carryHeldDrag }
}
