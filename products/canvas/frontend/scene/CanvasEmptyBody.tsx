import { useActions, useValues } from 'kea'

import { useInCanvasExperiment } from 'lib/hooks/useInCanvasExperiment'

import { CanvasComposer } from './CanvasComposer'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasStartHero } from './CanvasStartHero'

/** The body of a canvas with nothing to render yet: the composer that starts its first build. */
export function CanvasEmptyBody({ notice }: { notice?: string }): JSX.Element {
    const { instruction, instructionFromSuggestion, generationStarting } = useValues(canvasSceneLogic)
    const { setInstruction, generateCanvas } = useActions(canvasSceneLogic)
    const inExperiment = useInCanvasExperiment()

    // Experiment users have no composer, so the notice replaces the prompt to describe the canvas.
    if (inExperiment) {
        return (
            <CanvasStartHero
                title="Nothing to show yet"
                description="Ask your agent to build this canvas with the PostHog MCP server."
            >
                {null}
            </CanvasStartHero>
        )
    }

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
