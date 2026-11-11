import { useActions, useValues } from 'kea'

import { IconApps } from '@posthog/icons'
import {
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

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

/** The start page for a new canvas. Nothing is saved until the first prompt is sent, or until Start blank. */
export function CanvasNewScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { instruction, sending, sendDisabledReason, startingBlank, startBlankDisabledReason } =
        useValues(canvasNewLogic)
    const { setInstruction, send, startBlank } = useActions(canvasNewLogic)
    const blankDisabledReason = startBlankDisabledReason ?? (sending ? 'Wait for the canvas to be created.' : null)

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
                <CanvasStartHero description="Describe it and an agent builds it, or start blank and add blocks yourself.">
                    <CanvasComposer
                        instruction={instruction}
                        onInstructionChange={setInstruction}
                        onSubmit={send}
                        submitting={sending}
                        disabledReason={startingBlank ? 'Wait for the canvas to be created.' : sendDisabledReason}
                        footerStart={<CanvasSpaceSelect />}
                    />
                    <section aria-labelledby="canvas-build-yourself-label" className="flex flex-col gap-2">
                        <Text
                            id="canvas-build-yourself-label"
                            size="xs"
                            variant="muted"
                            weight="medium"
                            render={<h2 />}
                        >
                            Build it yourself
                        </Text>
                        <Tooltip>
                            {/* A disabled button gets no pointer events, so a span anchors the tooltip. */}
                            <TooltipTrigger delay={0} render={<span className="flex" />}>
                                <Item
                                    variant="outline"
                                    size="sm"
                                    className="w-full flex-nowrap bg-card text-left hover:bg-fill-hover"
                                    render={
                                        <button
                                            type="button"
                                            disabled={!!blankDisabledReason || startingBlank}
                                            aria-busy={startingBlank}
                                            onClick={() => startBlank()}
                                            data-attr="canvas-new-start-blank"
                                        />
                                    }
                                >
                                    <ItemMedia aria-hidden>
                                        <IconApps />
                                    </ItemMedia>
                                    <ItemContent className="min-w-0">
                                        <ItemTitle className="truncate">
                                            {startingBlank ? 'Creating the canvas…' : 'Blank'}
                                        </ItemTitle>
                                        <ItemDescription className="truncate">
                                            A title and a date range. Add blocks by hand.
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            </TooltipTrigger>
                            <TooltipContent>
                                {blankDisabledReason ?? 'Create an empty canvas and add blocks by hand'}
                            </TooltipContent>
                        </Tooltip>
                    </section>
                </CanvasStartHero>
            </main>
        </div>
    )
}
