import { useEffect, useState } from 'react'
import { TextMorph } from 'torph/react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

const VIEW_EMPTY_STATE_COPY = [
    'Resolving joins between your tables…',
    'Saving references to your tables…',
    'Searching saved queries for references…',
    'Fetching all references to optimize view…',
    'Constructing SQL expressions…',
]

export function ViewEmptyState(): JSX.Element {
    const [messageIndex, setMessageIndex] = useState(0)
    const { isVisible: isPageVisible } = usePageVisibility()

    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        const TOGGLE_INTERVAL = 3000

        const interval = setInterval(() => {
            setMessageIndex((current) => {
                let newIndex = Math.floor(Math.random() * VIEW_EMPTY_STATE_COPY.length)
                if (newIndex === current) {
                    newIndex = (newIndex + 1) % VIEW_EMPTY_STATE_COPY.length
                }
                return newIndex
            })
        }, TOGGLE_INTERVAL)

        return () => clearInterval(interval)
    }, [isPageVisible])

    return (
        <div data-attr="view-empty-state" className="flex flex-col flex-1 items-center justify-center">
            <TextMorph as="span" className="text-center">
                {VIEW_EMPTY_STATE_COPY[messageIndex]}
            </TextMorph>
        </div>
    )
}
