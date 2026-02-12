import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { productTourContentGenerationLogic } from './productTourContentGenerationLogic'

export interface ProductTourContentGenerationModalProps {
    tourId: string
}

export function ProductTourContentGenerationModal({ tourId }: ProductTourContentGenerationModalProps): JSX.Element {
    const { isModalOpen, goal, isGenerating, error } = useValues(productTourContentGenerationLogic({ tourId }))
    const { closeModal, setGoal, generateContent } = useActions(productTourContentGenerationLogic({ tourId }))

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title="Generate tour content"
            description="AI will write content for each step based on your tour's name, step context, and screenshots."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconSparkles />}
                        loading={isGenerating}
                        onClick={generateContent}
                    >
                        Generate
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                {isGenerating ? (
                    <div className="flex flex-col items-center justify-center gap-3 py-8">
                        <Spinner className="text-2xl" textColored />
                        <p className="text-muted text-sm m-0">Analyzing your tour steps and generating content...</p>
                    </div>
                ) : (
                    <>
                        <LemonTextArea
                            placeholder="e.g. Help users set up their first dashboard"
                            value={goal}
                            onChange={setGoal}
                            minRows={2}
                            maxRows={4}
                        />
                        <p className="text-muted text-xs m-0">
                            Describe what this tour should help users accomplish. Leave blank for general guidance.
                        </p>
                    </>
                )}

                {error && <LemonBanner type="error">{error}</LemonBanner>}
            </div>
        </LemonModal>
    )
}
