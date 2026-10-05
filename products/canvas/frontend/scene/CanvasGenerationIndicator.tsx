import { useValues } from 'kea'

import { Spinner, Text } from '@posthog/quill'

import { canvasSceneLogic } from './canvasSceneLogic'

/** A quiet note in the header while an agent works on a canvas that already shows something. */
export function CanvasGenerationIndicator(): JSX.Element | null {
    const { generationPhase, bodyState } = useValues(canvasSceneLogic)

    // A canvas with nothing to show says this in its body instead.
    if (!generationPhase || bodyState === 'generating') {
        return null
    }
    return (
        <div className="flex items-center gap-1.5" data-attr="canvas-generation-indicator">
            <Spinner />
            <Text size="xs" variant="muted" className="quill-shimmer">
                {generationPhase === 'starting' ? 'Starting the agent' : 'The agent is editing'}
            </Text>
        </div>
    )
}
