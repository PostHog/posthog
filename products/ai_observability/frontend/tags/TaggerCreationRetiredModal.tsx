import * as transformerPng from '@posthog/brand/hoggies/png/transformer'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

const HedgehogTransformer = pngHoggie(transformerPng)

export function TaggerCreationRetiredModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Taggers are deprecated in favor of evaluations"
            width={520}
            data-attr="tagger-creation-retired-modal"
        >
            <div className="flex flex-col items-center gap-4 text-center pb-2">
                <HedgehogTransformer className="w-28 h-28" />
                <p>New taggers can't be created. To tag generations, create an evaluation with a categorical output.</p>
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
