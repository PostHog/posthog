import { useActions, useValues } from 'kea'

import { CanvasComposer } from './CanvasComposer'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasStartHero } from './CanvasStartHero'

/** The body of a canvas with nothing to render yet: the composer that starts its first build. */
export function CanvasEmptyBody({ notice }: { notice?: string }): JSX.Element {
    const { instruction, instructionFromSuggestion, generationStarting } = useValues(canvasSceneLogic)
    const { setInstruction, generateCanvas } = useActions(canvasSceneLogic)

    return (
        <CanvasStartHero description={notice ?? 'Describe it and an agent builds it.'}>
            <CanvasComposer
                instruction={instruction}
                onInstructionChange={setInstruction}
                onSubmit={() => generateCanvas(instruction, instructionFromSuggestion)}
                submitting={generationStarting}
                disabledReason={instruction.trim() ? null : 'Describe the canvas first'}
            />
        </CanvasStartHero>
    )
}
