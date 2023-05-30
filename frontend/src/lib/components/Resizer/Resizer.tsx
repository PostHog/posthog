import { useActions, useValues } from 'kea'
import './Resizer.scss'
import { ResizerLogicProps, resizerLogic } from './resizerLogic'
import clsx from 'clsx'

export function Resizer(props: ResizerLogicProps): JSX.Element {
    const logic = resizerLogic(props)
    const { isResizeInProgress } = useValues(logic)
    const { beginResize } = useActions(logic)

    console.log({ isResizeInProgress })
    return (
        <div
            className={clsx('Resizer', isResizeInProgress && 'Resizer--resizing')}
            onMouseDown={(e) => {
                if (e.button === 0) {
                    beginResize(e)
                }
            }}
        >
            <div className="Resizer__handle" />
        </div>
    )
}
