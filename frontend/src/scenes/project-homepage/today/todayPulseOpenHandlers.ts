import type { MouseEvent } from 'react'

export interface PulseOpenHandlers {
    onClick: () => void
    onMouseDown: (event: MouseEvent<HTMLElement>) => void
    onAuxClick: (event: MouseEvent<HTMLElement>) => void
}

export function pulseOpenHandlers(onOpen: () => void): PulseOpenHandlers {
    return {
        onClick: onOpen,
        onMouseDown: (event) => {
            if (event.button === 0 && (event.metaKey || event.ctrlKey)) {
                onOpen()
            }
        },
        onAuxClick: (event) => {
            if (event.button === 1) {
                onOpen()
            }
        },
    }
}
