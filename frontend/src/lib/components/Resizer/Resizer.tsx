import { useActions, useValues } from 'kea'
import './Resizer.scss'
import { ResizerLogicProps, resizerLogic } from './resizerLogic'
import clsx from 'clsx'
import { useEffect, useState } from 'react'

export type ResizerProps = ResizerLogicProps & {
    offset?: number | string
}

export function Resizer(props: ResizerProps): JSX.Element {
    const logic = resizerLogic(props)
    const { isResizeInProgress } = useValues(logic)
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
            className={clsx(
                'Resizer',
                isResizeInProgress && isSelected && 'Resizer--resizing',
                `Resizer--${props.placement}`
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                [props.placement]: props.offset ?? 0,
            }}
            onMouseDown={(e) => {
                if (e.button === 0) {
                    setIsSelected(true)
                    beginResize(e.pageX)
                }
            }}
        >
            <div className="Resizer__handle" />
        </div>
    )
}
