import { HTMLAttributes, useEffect, useRef } from 'react'

export type UseDragAndDropResponse = {
    parentProps: {
        draggable?: HTMLAttributes<HTMLElement>['draggable']
        onDragStart?: HTMLAttributes<HTMLElement>['onDragStart']
        onDragEnd?: HTMLAttributes<HTMLElement>['onDragEnd']
    }

    handleProps: {
        onMouseDown?: HTMLAttributes<HTMLElement>['onMouseDown']
    }
}

export function useDragAndDrop(): UseDragAndDropResponse {
    const handleClickedRef = useRef(false)

    useEffect(() => {
        const onMouseUp = (): void => {
            handleClickedRef.current = false
        }

        document.addEventListener('mouseup', onMouseUp)
        return () => document.removeEventListener('mouseup', onMouseUp)
    }, [])

    const onMouseDown = (): void => {
        handleClickedRef.current = true
    }

    const onDragStart = (e: React.DragEvent<HTMLElement>): void => {
        if (!handleClickedRef.current) {
            e.preventDefault()
            return
        }

        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', '')
    }

    return {
        parentProps: {
            draggable: true,
            onDragStart: onDragStart,
            onDragEnd: (e) => {
                e.preventDefault()
            },
        },
        handleProps: {
            onMouseDown: onMouseDown,
        },
    }
}
