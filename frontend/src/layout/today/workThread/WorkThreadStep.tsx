import { useActions, useValues } from 'kea'
import { type ReactNode, useId } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Text,
    cn,
} from '@posthog/quill'

import type { WorkLineApi, WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { captureWorkStepToggled } from './workThreadEvents'
import { WorkThreadEvidence } from './WorkThreadEvidence'
import { workThreadLogic } from './workThreadLogic'
import { WorkThreadOptions } from './WorkThreadOptions'
import { isWorkStepExpanded, workStepState } from './workThreadState'
import { WorkThreadStepMarker } from './WorkThreadStepMarker'
import type { WorkRunActionHandler, WorkStepState } from './workThreadTypes'

const STATE_BADGE: Record<WorkStepState, { variant: 'completed' | 'warning' | 'default'; label: string }> = {
    done: { variant: 'completed', label: 'Done' },
    needs_you: { variant: 'warning', label: 'Needs you' },
    waiting: { variant: 'default', label: 'Waiting' },
}

interface WorkThreadStepProps {
    thread: WorkThreadApi
    line: WorkLineApi
    step: WorkStepApi
    renderEvidence?: (step: WorkStepApi) => JSX.Element | null
    onRunAction: WorkRunActionHandler
    /** The lines that run alongside this step, drawn under its card. */
    children?: ReactNode
}

function collapsedSummary(step: WorkStepApi): string {
    return [
        step.area,
        step.facts[0]?.value,
        step.chosen_label ? `You chose: ${step.chosen_label}` : null,
        step.alongside.length > 0 ? `${step.alongside.length} alongside` : null,
    ]
        .filter(Boolean)
        .join(' · ')
}

export function WorkThreadStep({
    thread,
    line,
    step,
    renderEvidence,
    onRunAction,
    children,
}: WorkThreadStepProps): JSX.Element {
    const logic = workThreadLogic({ threadKey: thread.key })
    const { expandedOverrides } = useValues(logic)
    const { setStepExpanded } = useActions(logic)
    const contentId = useId()

    const state = workStepState(line, step)
    const expanded = isWorkStepExpanded(state, expandedOverrides[step.key])
    const current = line.steps[line.steps.length - 1]?.key === step.key
    const badge = STATE_BADGE[state]
    const toggleLabel = expanded ? 'Collapse step' : 'Expand step'

    return (
        <li className="flex gap-3" data-attr="work-thread-step">
            <div className="flex shrink-0 flex-col items-center gap-1 pt-2.5">
                <WorkThreadStepMarker state={state} />
                {!current && <span aria-hidden className="w-px flex-1 bg-border" />}
            </div>
            <div className={cn('flex min-w-0 flex-1 flex-col gap-3', !current && 'pb-3')}>
                <Card size="sm">
                    <CardHeader>
                        <CardTitle className="min-w-0 break-words">{step.title}</CardTitle>
                        <CardDescription className={cn('min-w-0', expanded ? 'break-words' : 'truncate')}>
                            {expanded ? step.area : collapsedSummary(step)}
                        </CardDescription>
                        <CardAction className="flex items-center gap-2">
                            <Badge variant={badge.variant}>{badge.label}</Badge>
                            <Button
                                size="icon-sm"
                                aria-label={toggleLabel}
                                tooltip={toggleLabel}
                                aria-expanded={expanded}
                                aria-controls={expanded ? contentId : undefined}
                                onClick={() => {
                                    setStepExpanded(step.key, !expanded)
                                    captureWorkStepToggled(thread, step, !expanded)
                                }}
                                data-attr="work-thread-step-toggle"
                            >
                                {expanded ? <IconChevronDown /> : <IconChevronRight className="rtl:-scale-x-100" />}
                            </Button>
                        </CardAction>
                    </CardHeader>
                    {expanded && (
                        <CardContent id={contentId} className="flex flex-col gap-4">
                            <div className="flex flex-col gap-1">
                                {step.started_from && (
                                    <Text size="xs" variant="muted" className="m-0">
                                        {`Started from “${step.started_from.label}”. ${step.started_from.why}`}
                                    </Text>
                                )}
                                <Text size="xs" className="m-0">
                                    {step.description}
                                </Text>
                            </div>
                            <WorkThreadEvidence thread={thread} step={step} renderEvidence={renderEvidence} />
                            {current ? (
                                <WorkThreadOptions thread={thread} step={step} onRunAction={onRunAction} />
                            ) : (
                                step.chosen_label && (
                                    <Text size="xs" variant="muted" className="m-0">
                                        {`You chose “${step.chosen_label}”.`}
                                    </Text>
                                )
                            )}
                        </CardContent>
                    )}
                </Card>
                {children}
            </div>
        </li>
    )
}
