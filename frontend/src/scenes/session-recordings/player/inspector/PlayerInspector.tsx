import clsx from 'clsx'
import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useRef } from 'react'

import { PlayerInspectorControls } from './PlayerInspectorControls'
import { PlayerInspectorList } from './PlayerInspectorList'

export function PlayerInspector({
    isVerticallyStacked,
    onClose,
    toggleLayoutStacking,
}: {
    isVerticallyStacked: boolean
    onClose: (focus: boolean) => void
    toggleLayoutStacking?: () => void
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    const logicKey = `player-inspector-${isVerticallyStacked ? 'vertical' : 'horizontal'}`

    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: ref,
        persistent: true,
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'top' : 'left',
        onToggleClosed: (shouldBeClosed) => onClose(!shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            className={clsx('SessionRecordingPlayer__inspector')}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                isVerticallyStacked
                    ? { height: desiredSize ?? undefined, minHeight: 110 }
                    : { width: desiredSize ?? undefined }
            }
        >
            <Resizer
                logicKey={logicKey}
                placement={isVerticallyStacked ? 'top' : 'left'}
                containerRef={ref}
                closeThreshold={100}
            />
            <PlayerInspectorControls
                onClose={() => onClose(false)}
                isVerticallyStacked={isVerticallyStacked}
                toggleLayoutStacking={toggleLayoutStacking}
            />
            <PlayerInspectorList />
        </div>
    )
}
