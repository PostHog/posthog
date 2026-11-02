import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { Fragment } from 'react'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as officeWorkerPng from '@posthog/brand/hoggies/png/office-worker'
import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import * as stampApprovedPng from '@posthog/brand/hoggies/png/stamp-approved'
import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'

import { EvaluationCodeEditor } from '../components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from '../components/EvaluationPromptEditor'
import { EvaluationTriggersPanel } from '../components/EvaluationTriggersPanel'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'
import { EvaluationCreateButton } from './EvaluationCreateButton'
import { EvaluationCreateReview } from './EvaluationCreateReview'
import { EvaluationMethodPanel } from './EvaluationMethodPanel'
import { EvaluationModelPanel } from './EvaluationModelPanel'
import { EvaluationNameFields } from './EvaluationNameFields'
import { EvaluationOutputFields } from './EvaluationOutputFields'
import { EvaluationReportsPanel } from './EvaluationReportsPanel'
import { EvaluationReportsSwitch } from './EvaluationReportsSwitch'
import { EvaluationSentence, type SentencePart } from './EvaluationSentence'
import { EvaluationTargetPanel } from './EvaluationTargetPanel'
import { EvaluationVolumeEstimate } from './EvaluationVolumeEstimate'

interface Step {
    // pinned: analytics property value, because the creation funnel reads it
    key: 'name' | 'check' | 'traffic' | 'reports' | 'create'
    title: string
    heading: string
    /** One paragraph per entry. */
    description: string[]
    hoggie: ReturnType<typeof pngHoggie>
    /** The parts of the sentence this step edits. */
    parts: SentencePart[]
    /** The checklist items this step completes. */
    checks: ChecklistKey[]
}

const STEPS: Step[] = [
    {
        key: 'name',
        title: 'Name',
        heading: 'Name your evaluation',
        description: ['People see this name on results and reports.'],
        hoggie: pngHoggie(officeWorkerPng),
        parts: [],
        checks: ['name'],
    },
    {
        key: 'check',
        title: 'Check',
        heading: 'What it checks',
        description: ['Choose how each run gets checked, then write the instructions and pick what it returns.'],
        hoggie: pngHoggie(judgePng),
        parts: ['method', 'model'],
        checks: ['criteria', 'result', 'model'],
    },
    {
        key: 'traffic',
        title: 'Traffic',
        heading: 'What it runs on',
        description: ['Pick the live traffic it checks, and how much of it.'],
        hoggie: pngHoggie(magnifyingGlassPng),
        parts: ['target', 'triggers'],
        checks: ['sampling'],
    },
    {
        key: 'reports',
        title: 'Reports',
        heading: 'Reports',
        description: [
            'An agent reads the results and writes up what changed, with examples.',
            'Choose how often a report arrives and where it goes.',
        ],
        hoggie: pngHoggie(reporterPng),
        parts: ['reports'],
        checks: [],
    },
    {
        key: 'create',
        title: 'Create',
        heading: 'Ready to create',
        description: ['Everything it needs is set.'],
        hoggie: pngHoggie(stampApprovedPng),
        parts: [],
        checks: [],
    },
]

function StepContent({ step, isNew }: { step: Step['key']; isNew: boolean }): JSX.Element | null {
    const { evaluation, canEnable, canEnableReason } = useValues(llmEvaluationLogic)
    const { setEvaluationEnabled } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    switch (step) {
        case 'name':
            return (
                <>
                    <EvaluationNameFields />
                    {/* A new evaluation sets this on its create step. */}
                    {!isNew && (
                        <LemonSwitch
                            checked={evaluation.enabled}
                            onChange={setEvaluationEnabled}
                            disabledReason={
                                !canEnable && !evaluation.enabled ? (canEnableReason ?? undefined) : undefined
                            }
                            label={evaluation.enabled ? 'Running on new traffic' : 'Paused'}
                            bordered
                            data-attr="llma-evaluation-configuration-enabled"
                        />
                    )}
                </>
            )
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
        case 'create':
            return null
    }
}

/**
 * An evaluation's settings as steps, with the setup sentence above them as the overview of every choice so far.
 * Clicking a part of the sentence or a step goes straight there, so steps can be visited in any order. A new
 * evaluation ends on a create step. A saved one has no such step, because the page header saves it.
 */
export function EvaluationFormSteps({
    checklist,
    onCreate,
    onCancel,
}: {
    checklist: ChecklistItem[]
    /** Set for a new evaluation. Without it the steps edit a saved one. */
    onCreate?: () => void
    onCancel?: () => void
}): JSX.Element | null {
    const { evaluation, formStep } = useValues(llmEvaluationLogic)
    const { setFormStep } = useActions(llmEvaluationLogic)
    // Mounted here, not only in the name step, so moving between steps does not refetch the folders.
    useMountedLogic(llmEvaluationsLogic())

    if (!evaluation) {
        return null
    }
    const steps = onCreate ? STEPS : STEPS.filter((candidate) => candidate.key !== 'create')
    const index = Math.max(
        0,
        steps.findIndex((candidate) => candidate.key === formStep)
    )
    const step = steps[index]
    const isLast = index === steps.length - 1
    const isCreateStep = step.key === 'create'
    const todo = checklist.filter((item) => !item.done)
    const stepDone = (candidate: Step): boolean =>
        candidate.checks.every((key) => checklist.find((item) => item.key === key)?.done ?? true)
    const goTo = (next: number, via: 'next' | 'back' | 'sentence' | 'stepper'): void => {
        if (next === index) {
            return
        }
        // pinned: analytics event name and properties, because the creation funnel reads them
        posthog.capture('llma evaluation create step viewed', { step: steps[next].key, via, is_new: !!onCreate })
        setFormStep(steps[next].key)
    }
    const Hoggie = step.hoggie

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
            <nav className="flex flex-wrap items-center justify-center gap-2" aria-label="Steps">
                {steps.map((candidate, candidateIndex) => {
                    const current = candidateIndex === index
                    // A step counts as done once you have moved past it and nothing in it is missing.
                    const done = !current && candidateIndex < index && stepDone(candidate)
                    return (
                        <Fragment key={candidate.key}>
                            {candidateIndex > 0 && (
                                <span
                                    className={cn('h-px w-8 shrink-0', done ? 'bg-success' : 'bg-border')}
                                    aria-hidden
                                />
                            )}
                            <button
                                type="button"
                                onClick={() => goTo(candidateIndex, 'stepper')}
                                aria-current={current ? 'step' : undefined}
                                className="flex items-center gap-2 rounded px-1 py-0.5 cursor-pointer hover:bg-fill-highlight-100"
                                data-attr={`llma-evaluation-create-step-${candidate.key}`}
                            >
                                <span
                                    className={cn(
                                        'flex size-6 items-center justify-center rounded-full text-xs font-semibold',
                                        current
                                            ? 'bg-accent text-primary-inverse'
                                            : done
                                              ? 'text-success border border-success'
                                              : 'border text-secondary'
                                    )}
                                >
                                    {done ? <IconCheck /> : candidateIndex + 1}
                                </span>
                                <span className={cn('text-sm', current ? 'font-semibold' : 'text-secondary')}>
                                    {candidate.title}
                                </span>
                            </button>
                        </Fragment>
                    )
                })}
            </nav>
            <section
                className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6 flex flex-col gap-6 min-w-0"
                data-attr={`llma-evaluation-create-step-body-${step.key}`}
            >
                <div className="flex items-center gap-4">
                    <Hoggie className="w-16 shrink-0" />
                    <div className="flex flex-col gap-1 min-w-0 flex-1">
                        <h2 className="mb-0 text-lg font-semibold">
                            {isCreateStep && todo.length > 0 ? 'Almost there' : step.heading}
                        </h2>
                        {(isCreateStep && todo.length > 0
                            ? ['Finish the items below, then create it.']
                            : step.description
                        ).map((line) => (
                            <p key={line} className="mb-0 text-sm text-secondary">
                                {line}
                            </p>
                        ))}
                    </div>
                    {step.key === 'reports' && <EvaluationReportsSwitch />}
                </div>
                {!isCreateStep && (
                    <div className="flex flex-col gap-4 min-w-0">
                        <StepContent step={step.key} isNew={!!onCreate} />
                    </div>
                )}
                {isCreateStep && (
                    <EvaluationCreateReview
                        checklist={checklist}
                        onFix={(key) =>
                            goTo(
                                steps.findIndex((candidate) => candidate.checks.includes(key)),
                                'stepper'
                            )
                        }
                    />
                )}
                <div className="flex items-center justify-between gap-2">
                    {index > 0 ? (
                        <LemonButton type="tertiary" onClick={() => goTo(index - 1, 'back')}>
                            Back
                        </LemonButton>
                    ) : (
                        <span />
                    )}
                    <div className="flex items-center gap-2">
                        {onCancel && (
                            <LemonButton type="tertiary" onClick={onCancel}>
                                Cancel
                            </LemonButton>
                        )}
                        {isCreateStep && onCreate ? (
                            <EvaluationCreateButton
                                onCreate={onCreate}
                                disabledReason={todo[0]?.todo}
                                data-attr="llma-evaluation-create-submit"
                            />
                        ) : (
                            !isLast && (
                                <LemonButton
                                    type="primary"
                                    onClick={() => goTo(index + 1, 'next')}
                                    data-attr="llma-evaluation-create-next-step"
                                >
                                    {`Next: ${steps[index + 1].title}`}
                                </LemonButton>
                            )
                        )}
                    </div>
                </div>
            </section>
        </div>
    )
}
