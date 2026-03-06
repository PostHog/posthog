import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { visibilitySensorLogic } from './visibilitySensorLogic'

interface VisibilityProps {
    id: string // Must be unique for each component
    offset?: number
    children: React.ReactNode | null
}

export function VisibilitySensor({ id, offset, children }: VisibilityProps): JSX.Element {
    const { scrolling } = useActions(visibilitySensorLogic({ id, offset }))

    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        const element = ref.current
        const handler = (): void => {
            if (element) {
                scrolling(element)
            }
        }
        document.addEventListener('scroll', handler, { passive: true })
        return () => document.removeEventListener('scroll', handler)
    }, [ref.current]) // oxlint-disable-line react-hooks/exhaustive-deps

    return <div ref={ref}>{children}</div>
}
