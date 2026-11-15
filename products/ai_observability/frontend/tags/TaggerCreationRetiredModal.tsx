import * as transformerPng from '@posthog/brand/hoggies/png/transformer'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

const HedgehogTransformer = pngHoggie(transformerPng)

export type TaggerRetiredAction = 'create' | 'enable'

const MESSAGES: Record<TaggerRetiredAction, string> = {
    create: "New taggers can't be created. To tag generations, create an evaluation with a categorical output.",
    enable: "Switched-off taggers can't be turned back on. To keep tagging generations, create an evaluation with a categorical output.",
}

export function TaggerCreationRetiredModal({
    isOpen,
    onClose,
    action = 'create',
    inline = false,
}: {
    isOpen: boolean
    onClose: () => void
    action?: TaggerRetiredAction
    // Renders inline rather than in a portal, so Storybook can snapshot it.
    inline?: boolean
}): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            inline={inline}
            title="Taggers are deprecated in favor of evaluations"
            width={520}
            data-attr="tagger-creation-retired-modal"
        >
            <div className="flex flex-col items-center gap-4 text-center pb-2">
                <HedgehogTransformer className="w-28 h-28" />
                <p>{MESSAGES[action]}</p>
                <LemonButton
                    type="primary"
                    to={urls.aiObservabilityEvaluationTemplates()}
                    data-attr="tagger-creation-retired-create-evaluation"
                >
                    Create categorical evaluation
                </LemonButton>
            </div>
        </LemonModal>
    )
}
