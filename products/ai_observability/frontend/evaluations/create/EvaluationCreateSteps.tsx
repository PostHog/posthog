import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { EvaluationCodeEditor } from '../components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from '../components/EvaluationPromptEditor'
import { EvaluationTriggersPanel } from '../components/EvaluationTriggersPanel'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationMethodPanel } from './EvaluationMethodPanel'
import { EvaluationModelPanel } from './EvaluationModelPanel'
import { EvaluationNameFields } from './EvaluationNameFields'
import { EvaluationOutputFields } from './EvaluationOutputFields'
import { EvaluationReportsPanel } from './EvaluationReportsPanel'
import { EvaluationSentence, type SentencePart } from './EvaluationSentence'
import { EvaluationTargetPanel } from './EvaluationTargetPanel'
import { EvaluationVolumeEstimate } from './EvaluationVolumeEstimate'

interface Step {
    // pinned: analytics property value, because the creation funnel reads it
    key: 'name' | 'check' | 'traffic' | 'reports'
    title: string
    parts: SentencePart[]
}

const STEPS: Step[] = [
    { key: 'name', title: 'Name it', parts: [] },
    { key: 'check', title: 'What it checks', parts: ['method', 'model'] },
    { key: 'traffic', title: 'What it runs on', parts: ['target', 'triggers'] },
    { key: 'reports', title: 'Reports', parts: ['reports'] },
]

function StepContent({ step }: { step: Step['key'] }): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    switch (step) {
        case 'name':
            return <EvaluationNameFields />
        case 'check':
            return (
                <>
                    <EvaluationMethodPanel />
                    {evaluation.evaluation_type === 'llm_judge' && <EvaluationModelPanel />}
                    {evaluation.evaluation_type === 'llm_judge' && <EvaluationPromptEditor />}
                    {evaluation.evaluation_type === 'hog' && <EvaluationCodeEditor />}
                    <EvaluationOutputFields />
                </>
            )
        case 'traffic':
            return (
                <>
                    <EvaluationTargetPanel />
                    <div className="flex flex-col gap-2">
                        <h4 className="mb-0 text-base font-semibold">Triggers</h4>
                        <EvaluationTriggersPanel />
                    </div>
                    <EvaluationVolumeEstimate />
                </>
            )
        case 'reports':
            return <EvaluationReportsPanel />
    }
}

/**
 * The new evaluation form as steps under a pinned sentence. The sentence is the overview of every choice so far,
 * and clicking one of its parts goes to the step that edits it, so steps can be visited in any order.
 */
export function EvaluationCreateSteps(): JSX.Element {
    const [index, setIndex] = useState(0)
    const step = STEPS[index]
    const goTo = (next: number, via: 'next' | 'back' | 'sentence' | 'stepper'): void => {
        // pinned: analytics event name and properties, because the creation funnel reads them
        posthog.capture('llma evaluation create step viewed', { step: STEPS[next].key, via })
        setIndex(next)
    }

    return (
        <div className="flex flex-col gap-6">
            <EvaluationSentence
                activeParts={step.parts}
                onPartClick={(part) =>
                    goTo(
                        STEPS.findIndex((candidate) => candidate.parts.includes(part)),
                        'sentence'
                    )
                }
            />
            <nav className="flex flex-wrap items-center gap-1 border-b pb-2" aria-label="Steps">
                {STEPS.map((candidate, candidateIndex) => (
                    <LemonButton
                        key={candidate.key}
                        size="small"
                        type="tertiary"
                        active={candidateIndex === index}
                        onClick={() => goTo(candidateIndex, 'stepper')}
                        aria-current={candidateIndex === index ? 'step' : undefined}
                        data-attr={`llma-evaluation-create-step-${candidate.key}`}
                    >
                        <span className={candidateIndex === index ? 'font-semibold' : 'text-secondary'}>
                            {`${candidateIndex + 1}. ${candidate.title}`}
                        </span>
                    </LemonButton>
                ))}
            </nav>
            <section className="flex flex-col gap-4 min-w-0" data-attr={`llma-evaluation-create-step-body-${step.key}`}>
                <StepContent step={step.key} />
            </section>
            <div className="flex justify-between gap-2">
                {index > 0 ? (
                    <LemonButton type="secondary" onClick={() => goTo(index - 1, 'back')}>
                        Back
                    </LemonButton>
                ) : (
                    <span />
                )}
                {index < STEPS.length - 1 && (
                    <LemonButton
                        type="primary"
                        onClick={() => goTo(index + 1, 'next')}
                        data-attr="llma-evaluation-create-next-step"
                    >
                        {`Next: ${STEPS[index + 1].title}`}
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
