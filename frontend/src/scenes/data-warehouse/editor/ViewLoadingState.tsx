import { useState } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const VIEW_EMPTY_STATE_COPY = [
    'Resolving joins between your tables…',
    'Saving references to your tables…',
    'Searching saved queries for references…',
    'Fetching all references to optimize view…',
    'Constructing SQL expressions…',
]

export function ViewEmptyState(): JSX.Element {
    const [messageIndex, setMessageIndex] = useState(0)
    const [isMessageVisible, setIsMessageVisible] = useState(true)

    useOnMountEffect(() => {
        const TOGGLE_INTERVAL = 3000
        const FADE_OUT_DURATION = 300

        const interval = setInterval(() => {
            setIsMessageVisible(false)
            setTimeout(() => {
                setMessageIndex((current) => {
                    let newIndex = Math.floor(Math.random() * VIEW_EMPTY_STATE_COPY.length)
                    if (newIndex === current) {
                        newIndex = (newIndex + 1) % VIEW_EMPTY_STATE_COPY.length
                    }
                    return newIndex
                })
                setIsMessageVisible(true)
            }, FADE_OUT_DURATION)
        }, TOGGLE_INTERVAL)

        return () => clearInterval(interval)
    })

    return (
        <div data-attr="view-empty-state" className="flex flex-col flex-1 items-center justify-center">
            <span
                className={`text-center transition-opacity duration-300 ${
                    isMessageVisible ? 'opacity-100' : 'opacity-0'
                }`}
            >
                {VIEW_EMPTY_STATE_COPY[messageIndex]}
            </span>
        </div>
    )
}
