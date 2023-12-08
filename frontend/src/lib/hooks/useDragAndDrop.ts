import { HTMLAttributes, useEffect, useRef } from 'react'

export type UseDragAndDropOptions = {
    onDragStart: (e: React.DragEvent<HTMLElement>) => void
}

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

export function useDragAndDrop(props: UseDragAndDropOptions): UseDragAndDropResponse {
    const handleClickedRef = useRef(false)

    useEffect(() => {
        const onMouseUp = (): void => {
            handleClickedRef.current = false
        }

        window.addEventListener('mouseup', onMouseUp)
        return () => window.removeEventListener('mouseup', onMouseUp)
    }, [])

    const onMouseDown = (): void => {
        handleClickedRef.current = true
    }

    const onDragStart = (e: React.DragEvent<HTMLElement>): void => {
        if (!handleClickedRef.current) {
            e.preventDefault()
            return
        }

        handleClickedRef.current = false
        props.onDragStart(e)
    }

    return {
        parentProps: {
            draggable: true,
            onDragStart: onDragStart,
            onDragEnd: (e) => {},
        },
        handleProps: {
            onMouseDown: onMouseDown,
        },
    }
}
