import './Resizer.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import { ResizerLogicProps, resizerLogic } from './resizerLogic'

export type ResizerProps = ResizerLogicProps & {
    offset?: number | string
    className?: string
}

export function Resizer(props: ResizerProps): JSX.Element {
    const logic = resizerLogic(props)
    const { isResizeInProgress, isVertical } = useValues(logic)
    const { beginResize } = useActions(logic)

    // The same logic can be used by multiple resizers
    const [isSelected, setIsSelected] = useState(false)

    useEffect(() => {
        if (!isResizeInProgress) {
            setIsSelected(false)
        }
    }, [isResizeInProgress])

    return (
        <div
            className={cn(
                'Resizer',
                isResizeInProgress && isSelected && 'Resizer--resizing',
                `Resizer--${props.placement}`,
                props.className
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                [props.placement]: props.offset ?? 0,
            }}
            onMouseDown={(e) => {
                if (e.button === 0) {
                    setIsSelected(true)
                    beginResize(isVertical ? e.pageX : e.pageY)
                }
            }}
        >
            <div className="Resizer__handle" />
        </div>
    )
}
