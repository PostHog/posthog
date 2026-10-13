import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { SuggestionCard } from 'scenes/max/components/SuggestionCard'

import { runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'
import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { AiFirstHandoffLogicProps, aiFirstHandoffLogic } from './aiFirstHandoffLogic'

export interface AiFirstSuggestion {
    title: string
    description: string
    prompt: string
}

export interface AiFirstCreateSceneProps {
    handoff: AiFirstHandoffLogicProps
    /** Banner copy that says what this page trials. */
    banner: string
    escapeHatchLabel: string
    onEscapeHatch: () => void
    suggestions: AiFirstSuggestion[]
    suggestionIcon: JSX.Element
    /** Rendered between the composer and the suggestions while no run is active, e.g. a row of starting points. */
    belowComposer?: React.ReactNode
    // pinned: `data-attr` root. The page, its escape hatch (`-open-editor`) and its cards (`-suggestion`) hang off it.
    dataAttr: string
}

/** An AI-first "new entity" page: the side panel's runner rendered full page, with a way back to the editor. */
export function AiFirstCreateScene({
    handoff,
    banner,
    escapeHatchLabel,
    onEscapeHatch,
    suggestions,
    suggestionIcon,
    belowComposer,
    dataAttr,
}: AiFirstCreateSceneProps): JSX.Element {
    const { composerShown, escapeHatchClicked, fillComposer } = useActions(aiFirstHandoffLogic(handoff))
    useEffect(() => composerShown(), [composerShown])
    const { activeCreation } = useValues(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }))

    return (
        // Natural height while drafting so the cards sit under the composer; full page once a run starts.
        <div className="flex flex-col grow min-h-0" data-attr={dataAttr}>
            {/* The escape hatch stays up during a run, so a turn that never creates the entity has a way out. */}
            <LemonBanner
                type="ai"
                className="m-2 shrink-0"
                action={{
                    children: escapeHatchLabel,
                    onClick: () => {
                        escapeHatchClicked()
                        onEscapeHatch()
                    },
                    'data-attr': `${dataAttr}-open-editor`,
                }}
            >
                {banner}
            </LemonBanner>
            <div className={cn('flex flex-col', activeCreation ? 'grow min-h-0' : 'shrink-0 mt-auto')}>
                <SidePanelRunner panelId={MAX_SIDE_PANEL_ID} />
            </div>
            {!activeCreation && (
                <div className="flex flex-col items-center gap-4 shrink-0 pb-6 mb-auto">
                    {belowComposer}
                    <div className="grid grid-cols-1 @min-[40rem]/main-content:grid-cols-2 gap-1 w-full max-w-2xl px-4">
                        {suggestions.map((suggestion) => (
                            <SuggestionCard
                                key={suggestion.prompt}
                                title={suggestion.title}
                                description={suggestion.description}
                                icon={suggestionIcon}
                                onClick={() => fillComposer(suggestion.prompt)}
                                data-attr={`${dataAttr}-suggestion`}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
