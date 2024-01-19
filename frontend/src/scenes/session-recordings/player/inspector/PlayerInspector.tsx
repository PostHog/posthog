import clsx from 'clsx'
import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useEffect, useRef, useState } from 'react'

import { PlayerInspectorControls } from './PlayerInspectorControls'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorPreview } from './PlayerInspectorPreview'

export function PlayerInspector({
    isWidescreen,
    onFocusChange,
}: {
    isWidescreen: boolean
    onFocusChange: (focus: boolean) => void
}): JSX.Element {
    const [inspectorFocus, setInspectorFocus] = useState(false)
    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'player-inspector',
        persistent: true,
        closeThreshold: 100,
        placement: 'left',
        onToggleClosed: (shouldBeClosed) => {
            setInspectorFocus(!shouldBeClosed)
            // shouldBeClosed ? closeSidePanel() : selectedTab ? openSidePanel(selectedTab) : undefined
        },
    }

    const { desiredWidth } = useValues(resizerLogic(resizerLogicProps))

    useEffect(() => {
        onFocusChange(inspectorFocus)
    }, [inspectorFocus])

    return (
        <div
            className={clsx(
                'SessionRecordingPlayer__inspector',
                !inspectorFocus && 'SessionRecordingPlayer__inspector--collapsed'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: inspectorFocus ? desiredWidth ?? '2.5rem' : undefined,
            }}
        >
            <Resizer
                logicKey="player-inspector"
                placement="left"
                containerRef={ref}
                closeThreshold={100}
                disabled={isWidescreen}
                // onToggleClosed={(shouldBeClosed) => toggleNavCollapsed(shouldBeClosed)}
                // onDoubleClick={() => toggleNavCollapsed()}
            />
            {inspectorFocus || isWidescreen ? (
                <>
                    <PlayerInspectorControls />
                    <PlayerInspectorList />
                </>
            ) : (
                <PlayerInspectorPreview onClick={() => setInspectorFocus(true)} />
            )}
        </div>
    )
}
