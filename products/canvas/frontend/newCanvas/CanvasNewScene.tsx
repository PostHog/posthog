import { useActions, useValues } from 'kea'

import { IconPalette } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CanvasComposer } from '../scene/CanvasComposer'
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
        <SceneContent>
            <SceneTitleSection
                name="New canvas"
                description="Describe what you want and an agent builds it. The canvas is saved when you send."
                resourceType={{ type: 'canvas', forceIcon: <IconPalette /> }}
            />
            <div data-quill className="w-full max-w-3xl">
                <CanvasComposer
                    instruction={instruction}
                    onInstructionChange={setInstruction}
                    onSubmit={send}
                    submitting={sending}
                    disabledReason={sendDisabledReason}
                    footerStart={<CanvasSpaceSelect />}
                />
            </div>
        </SceneContent>
    )
}
