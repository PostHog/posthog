import { actions, kea, listeners, path, reducers } from 'kea'

import type { floatingMaxPositionLogicType } from './floatingMaxPositionLogicType'

export interface FloatingMaxPosition {
    side: 'left' | 'right'
}

const FLOATING_MAX_POSITION_STORAGE_KEY = 'floating_max_position'

export const floatingMaxPositionLogic = kea<floatingMaxPositionLogicType>([
    path(['scenes', 'max', 'floatingMaxPositionLogic']),

    actions({
        setPosition: (position: FloatingMaxPosition) => ({ position }),
    }),

    reducers({
        position: [
            { side: 'right' } as FloatingMaxPosition,
            {
                setPosition: (_, { position }) => position,
            },
        ],
    }),

    listeners(({ actions }) => ({
        setPosition: ({ position }) => {
            // Persist position to localStorage
            try {
                localStorage.setItem(FLOATING_MAX_POSITION_STORAGE_KEY, JSON.stringify(position))
            } catch {
                // Ignore localStorage errors
            }
        },
        afterMount: () => {
            // Load position from localStorage on mount
            try {
                const stored = localStorage.getItem(FLOATING_MAX_POSITION_STORAGE_KEY)
                if (stored) {
                    const position = JSON.parse(stored)
                    if (position && (position.side === 'left' || position.side === 'right')) {
                        actions.setPosition(position)
                    }
                }
            } catch {
                // Ignore localStorage errors, use default position
            }
        },
    })),
])
