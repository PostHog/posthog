import { Resizer } from 'lib/components/Resizer/Resizer'
import { useEffect, useRef, useState } from 'react'

import { PlayerInspectorControls } from './PlayerInspectorControls'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorPreview } from './PlayerInspectorPreview'

export function PlayerInspector({ onFocusChange }: { onFocusChange: (focus: boolean) => void }): JSX.Element {
    const [inspectorFocus, setInspectorFocus] = useState(false)

    useEffect(() => {
        onFocusChange(inspectorFocus)
    }, [inspectorFocus])

    const ref = useRef<HTMLDivElement>(null)

    return (
        <div className="SessionRecordingPlayer__inspector" ref={ref}>
            <Resizer logicKey="player-inspector" placement="left" containerRef={ref} />
            <PlayerInspectorControls />
            <PlayerInspectorList />
            <PlayerInspectorPreview onClick={() => setInspectorFocus(true)} />
        </div>
    )
}
