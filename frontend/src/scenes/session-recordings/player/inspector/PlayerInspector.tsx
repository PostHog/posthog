import { LemonDivider } from '@posthog/lemon-ui'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorControls } from './PlayerInspectorControls'

export function PlayerInspector(): JSX.Element {
    return (
        <>
            <PlayerInspectorControls />
            <LemonDivider className="my-0" />
            <PlayerInspectorList />
        </>
    )
}
