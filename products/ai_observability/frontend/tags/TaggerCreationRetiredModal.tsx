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
            title="Tag generations with an evaluation"
            width={480}
            data-attr="tagger-creation-retired-modal"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={urls.aiObservabilityEvaluationTemplates()}
                        data-attr="tagger-creation-retired-create-evaluation"
                    >
                        Create a categorical evaluation
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col items-center gap-4 text-center">
                <HedgehogTransformer className="w-32 h-32" />
                <p>
                    New taggers can't be created. Evaluations with a categorical output do the same job: each tag
                    becomes a category, and the evaluation can pick more than one per generation.
                </p>
                <p className="text-secondary">
                    Your existing taggers keep running for now, and we'll let you know before they stop.
                </p>
            </div>
        </LemonModal>
    )
}
