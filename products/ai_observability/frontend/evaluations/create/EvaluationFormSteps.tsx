import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { Fragment } from 'react'

import * as judgePng from '@posthog/brand/hoggies/png/judge'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as officeWorkerPng from '@posthog/brand/hoggies/png/office-worker'
import * as organizedPng from '@posthog/brand/hoggies/png/organized'
import * as reporterPng from '@posthog/brand/hoggies/png/reporter'
import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'

import { TraceDrawerHost } from '../../redesign/trace/TraceDrawerHost'
import { EvaluationCodeEditor } from '../components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from '../components/EvaluationPromptEditor'
import { EvaluationTriggersPanel } from '../components/EvaluationTriggersPanel'
import { evaluationPreviewLogic } from '../evaluationPreviewLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import type { ChecklistItem, ChecklistKey } from './creationChecklist'
import { EvaluationCreateButton } from './EvaluationCreateButton'
import { EvaluationLivePreview } from './EvaluationLivePreview'
import { EvaluationMethodPanel } from './EvaluationMethodPanel'
import { EvaluationModelPanel } from './EvaluationModelPanel'
import { EvaluationNameFields } from './EvaluationNameFields'
import { EvaluationOutputFields } from './EvaluationOutputFields'
import { EvaluationReportsPanel } from './EvaluationReportsPanel'
import { EvaluationReportsSwitch } from './EvaluationReportsSwitch'
import { EvaluationTargetPanel } from './EvaluationTargetPanel'
import { EvaluationVolumeEstimate } from './EvaluationVolumeEstimate'
import { PREVIEW_DRAWER_LIST_ID } from './previewRuns'

interface Step {
    // pinned: analytics property value, because the creation funnel reads it
    key: 'name' | 'output' | 'check' | 'traffic' | 'reports'
    title: string
    heading: string
    /** One paragraph per entry. */
    description: string[]
    hoggie: ReturnType<typeof pngHoggie>
    /** pinned: the `llma-evaluation-create-part-*` data-attr and analytics value, read by the creation funnel. */
    part: string
    /** The checklist items this step completes. */
    checks: ChecklistKey[]
    /** Shown as optional in the stepper, because the evaluation works without it. */
    optional?: boolean
}

const STEPS: Step[] = [
    {
        key: 'name',
        title: 'Evaluate',
        heading: 'What it evaluates',
        description: ['Name it and choose how it decides.'],
        hoggie: pngHoggie(officeWorkerPng),
        part: 'method',
        checks: ['name'],
    },
    {
        key: 'output',
        title: 'Returns',
        heading: 'What it returns',
        description: ['Choose what each run returns, and which results count as a pass.'],
        hoggie: pngHoggie(organizedPng),
        part: 'output',
        checks: ['result'],
    },
    {
        key: 'traffic',
        title: 'Runs on',
        heading: 'What it runs on',
        description: ['Choose what one run covers and which traffic it checks.'],
        hoggie: pngHoggie(magnifyingGlassPng),
        part: 'triggers',
        checks: ['sampling'],
    },
    {
        key: 'check',
        title: 'Check',
        heading: 'How it checks',
        description: ['Write the prompt or the code that decides each result.'],
        hoggie: pngHoggie(judgePng),
        part: 'model',
        checks: ['criteria', 'model'],
    },
    {
        key: 'reports',
        title: 'Reports',
        heading: 'Reports',
        description: ['An agent writes up what changed in the results, with examples.'],
        hoggie: pngHoggie(reporterPng),
        part: 'reports',
        checks: [],
        optional: true,
    },
]

function StepContent({ step }: { step: Step['key'] }): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    switch (step) {
        case 'name':
            return (
                <>
                    <EvaluationNameFields />
                    <EvaluationMethodPanel />
                </>
            )
        case 'output':
            return <EvaluationOutputFields />
        case 'traffic':
            return (
                <>
                    <EvaluationTargetPanel />
                    <div className="flex flex-col gap-3">
                        <EvaluationTriggersPanel />
                        {/* What the filters match, right under them, so changing a filter shows its effect in place. */}
                        <div className="rounded bg-fill-highlight-50 px-3 py-2">
                            <EvaluationVolumeEstimate />
                        </div>
                    </div>
                </>
            )
        case 'check':
            return (
                <>
                    {evaluation.evaluation_type === 'llm_judge' && <EvaluationModelPanel />}
                    {evaluation.evaluation_type === 'llm_judge' && <EvaluationPromptEditor />}
                    {evaluation.evaluation_type === 'hog' && <EvaluationCodeEditor />}
                </>
            )
        case 'reports':
            return <EvaluationReportsPanel />
    }
}

/**
 * An evaluation's settings as steps, next to a live preview of what it does. Clicking a part of the preview or a step
 * goes straight there, so steps can be visited in any order. A new evaluation is created from the last step; a saved
 * one is saved from the page header.
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
    // Mounted here, not only in the steps that use them, so moving between steps keeps the folders and the traffic.
    useMountedLogic(llmEvaluationsLogic())
    const { props } = useMountedLogic(llmEvaluationLogic)
    useMountedLogic(evaluationPreviewLogic(props))

    if (!evaluation) {
        return null
    }
    // Sentiment has a fixed answer and no prompt, code, or model to set, so it skips those steps.
    const steps = STEPS.filter(
        (candidate) =>
            evaluation.evaluation_type !== 'sentiment' || (candidate.key !== 'check' && candidate.key !== 'output')
    )
    const index = Math.max(
        0,
        steps.findIndex((candidate) => candidate.key === formStep)
    )
    const step = steps[index]
    const isLast = index === steps.length - 1
    const todo = checklist.filter((item) => !item.done)
    const stepDone = (candidate: Step): boolean =>
        candidate.checks.every((key) => checklist.find((item) => item.key === key)?.done ?? true)
    const stepWarned = (candidate: Step): boolean =>
        candidate.checks.some((key) => !!checklist.find((item) => item.key === key && item.done)?.warning)
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
            <nav className="flex flex-wrap items-center justify-center gap-2" aria-label="Steps">
                {steps.map((candidate, candidateIndex) => {
                    const current = candidateIndex === index
                    // A step counts as done once you have moved past it and nothing in it is missing. A warning
                    // shows from any step, because the traffic it is about can change while you are elsewhere.
                    const warned = !current && stepWarned(candidate)
                    const done = !current && !warned && candidateIndex < index && stepDone(candidate)
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
                                            : warned
                                              ? 'text-warning border border-warning'
                                              : done
                                                ? 'text-success border border-success'
                                                : 'border text-secondary'
                                    )}
                                >
                                    {warned ? <IconWarning /> : done ? <IconCheck /> : candidateIndex + 1}
                                </span>
                                <span className={cn('text-sm', current ? 'font-semibold' : 'text-secondary')}>
                                    {candidate.title}
                                </span>
                                {candidate.optional && <span className="text-xs text-secondary">Optional</span>}
                            </button>
                        </Fragment>
                    )
                })}
            </nav>
            {/* Two columns from the width a 1024px window leaves beside the navigation, so the preview stays next
                to what is being edited. The panel is narrower there, to leave the editor room. */}
            <div className="grid grid-cols-1 items-start gap-4 @min-[44rem]/evaluation:grid-cols-[minmax(0,1fr)_17rem] @min-[60rem]/evaluation:grid-cols-[minmax(0,1fr)_22rem]">
                <section
                    className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6 flex flex-col gap-6 min-w-0"
                    data-attr={`llma-evaluation-create-step-body-${step.key}`}
                >
                    <div className="flex items-center gap-4">
                        <Hoggie className="w-16 shrink-0" />
                        <div className="flex flex-col gap-1 min-w-0 flex-1">
                            <h2 className="mb-0 text-lg font-semibold">{step.heading}</h2>
                            {step.description.map((line) => (
                                <p key={line} className="mb-0 text-sm text-secondary">
                                    {line}
                                </p>
                            ))}
                        </div>
                        {step.key === 'reports' && <EvaluationReportsSwitch />}
                    </div>
                    <div className="flex flex-col gap-4 min-w-0">
                        <StepContent step={step.key} />
                    </div>
                    <div className="flex items-center justify-between gap-2">
                        {index > 0 ? (
                            <LemonButton type="secondary" onClick={() => goTo(index - 1, 'back')}>
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
                            {isLast && onCreate ? (
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
                <EvaluationLivePreview
                    steps={steps}
                    currentIndex={index}
                    checklist={checklist}
                    onGo={(target) => goTo(target, 'sentence')}
                    onCreate={onCreate}
                />
            </div>
            <TraceDrawerHost listId={PREVIEW_DRAWER_LIST_ID} />
        </div>
    )
}
