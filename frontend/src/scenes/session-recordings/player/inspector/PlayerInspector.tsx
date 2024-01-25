import clsx from 'clsx'
import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useRef } from 'react'

import { PlayerInspectorControls } from './PlayerInspectorControls'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorPreview } from './PlayerInspectorPreview'

export function PlayerInspector({
    inspectorExpanded,
    setInspectorExpanded,
}: {
    inspectorExpanded: boolean
    setInspectorExpanded: (focus: boolean) => void
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'player-inspector',
        persistent: true,
        closeThreshold: 100,
        placement: 'left',
        onToggleClosed: (shouldBeClosed) => setInspectorExpanded(!shouldBeClosed),
    }

    const { desiredWidth } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            className={clsx(
                'SessionRecordingPlayer__inspector',
                !inspectorExpanded && 'SessionRecordingPlayer__inspector--collapsed'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: inspectorExpanded ? desiredWidth ?? 'var(--inspector-width)' : undefined,
            }}
        >
            <Resizer logicKey="player-inspector" placement="left" containerRef={ref} closeThreshold={100} />
            {inspectorExpanded ? (
                <>
                    <PlayerInspectorControls onClose={() => setInspectorExpanded(false)} />
                    <PlayerInspectorList />
                </>
            ) : (
                <PlayerInspectorPreview onClick={() => setInspectorExpanded(true)} />
            )}
        </div>
    )
}
