import { useActions } from 'kea'
import React, { useRef } from 'react'
import { visibilitySensorLogic } from './visibilitySensorLogic'

interface VisibilityProps {
    id: string
    offset: number
    children: React.ReactNode | null
}

export function VisibilitySensor({ id, offset, children }: VisibilityProps): JSX.Element {
    const { setElementRef } = useActions(visibilitySensorLogic({ id, offset }))

    const ref = useRef<HTMLDivElement | null>(null)

    setElementRef(ref)

    return <div ref={ref}>{children}</div>
}
