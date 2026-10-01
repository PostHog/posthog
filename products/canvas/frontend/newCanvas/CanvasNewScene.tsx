import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { CanvasComposer } from '../scene/CanvasComposer'
import { CanvasStartHero } from '../scene/CanvasStartHero'
import { CanvasToolbar } from '../scene/CanvasToolbar'
import { canvasNewLogic } from './canvasNewLogic'
import { CanvasSpaceSelect } from './CanvasSpaceSelect'

export const scene: SceneExport = {
    component: CanvasNewScene,
    logic: canvasNewLogic,
}

/** The start page for a new canvas. Nothing is saved until the first prompt is sent. */
export function CanvasNewScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { instruction, sending, sendDisabledReason } = useValues(canvasNewLogic)
    const { setInstruction, send } = useActions(canvasNewLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }
    return (
        <div data-quill className="flex h-full min-h-0 flex-col bg-background">
            <CanvasToolbar dataAttr="canvas-new-toolbar">
                <Text size="sm" weight="medium" className="truncate pl-2">
                    New canvas
                </Text>
            </CanvasToolbar>
            <main className="min-h-0 flex-1">
                <CanvasStartHero description="Describe it and an agent builds it. The canvas is saved when you send.">
                    <CanvasComposer
                        instruction={instruction}
                        onInstructionChange={setInstruction}
                        onSubmit={send}
                        submitting={sending}
                        disabledReason={sendDisabledReason}
                        footerStart={<CanvasSpaceSelect />}
                    />
                </CanvasStartHero>
            </main>
        </div>
    )
}
