import { useActions } from 'kea'
import React, { useEffect, useRef } from 'react'
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
        document.addEventListener('scroll', () => scrolling(element))
        return () => document.removeEventListener('scroll', () => scrolling(element))
    }, [ref.current])

    return <div ref={ref}>{children}</div>
}
