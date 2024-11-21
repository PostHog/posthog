import { useMountedLogic } from 'kea'

import { embeddedReplayLogic } from './embeddedReplayLogic'

export function EmbeddedReplayHelper(): JSX.Element {
    // NOTE: This is a helper component to avoid circular imports from the logic
    useMountedLogic(embeddedReplayLogic)
    return <></>
}
