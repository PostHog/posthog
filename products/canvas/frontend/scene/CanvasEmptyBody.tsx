import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { CanvasComposer } from './CanvasComposer'
import { canvasSceneLogic } from './canvasSceneLogic'

/** The body of a canvas with nothing to render yet: the composer that starts its first build. */
export function CanvasEmptyBody({ notice }: { notice?: string }): JSX.Element {
    const { instruction, instructionFromSuggestion, generationStarting } = useValues(canvasSceneLogic)
    const { setInstruction, generateCanvas } = useActions(canvasSceneLogic)

    return (
        <div className="h-full overflow-y-auto">
            <div className="flex w-full max-w-3xl flex-col gap-4 py-2">
                <Text size="sm" variant="muted">
                    {notice ?? 'Describe what you want and an agent builds it.'}
                </Text>
                <CanvasComposer
                    instruction={instruction}
                    onInstructionChange={setInstruction}
                    onSubmit={() => generateCanvas(instruction, instructionFromSuggestion)}
                    submitting={generationStarting}
                    disabledReason={instruction.trim() ? null : 'Describe the canvas first'}
                />
            </div>
        </div>
    )
}
