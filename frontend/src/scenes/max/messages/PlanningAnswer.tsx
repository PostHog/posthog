import clsx from 'clsx'
import { useLayoutEffect, useState } from 'react'

import { IconChevronRight, IconNotebook } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'

import { useQuillThread } from 'products/posthog_ai/frontend/api/primitives'

import { ShimmeringContent } from '../components/Activity'
import { EnhancedToolCall } from '../max-constants'
import { parsePlanningSteps } from './planningSteps'
import { QuillPlanningAnswer } from './quill/QuillPlanningAnswer'

export interface PlanningAnswerProps {
    toolCall: EnhancedToolCall
    isLastPlanningMessage?: boolean
}

export function PlanningAnswer(props: PlanningAnswerProps): JSX.Element {
    return useQuillThread() ? <QuillPlanningAnswer {...props} /> : <LemonPlanningAnswer {...props} />
}

function LemonPlanningAnswer({ toolCall, isLastPlanningMessage = true }: PlanningAnswerProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(isLastPlanningMessage)

    useLayoutEffect(() => {
        setIsExpanded(isLastPlanningMessage)
    }, [isLastPlanningMessage])

    const steps = parsePlanningSteps(toolCall)
    const completedCount = steps.filter((step) => step.status === 'completed').length
    const totalCount = steps.length
    const hasMultipleSteps = steps.length > 1

    return (
        <div className="flex flex-col text-xs">
            <div
                className={clsx(
                    'flex items-center select-none',
                    !hasMultipleSteps ? 'cursor-default' : 'cursor-pointer'
                )}
                onClick={!hasMultipleSteps ? undefined : () => setIsExpanded(!isExpanded)}
                aria-label={!hasMultipleSteps ? undefined : isExpanded ? 'Collapse plan' : 'Expand plan'}
            >
                <div className="flex items-center justify-center size-5">
                    <IconNotebook />
                </div>
                <div className="flex items-center gap-1.5 flex-1 min-w-0">
                    <span>Planning</span>
                    <span className="text-muted">
                        ({completedCount}/{totalCount})
                    </span>
                    {hasMultipleSteps && (
                        <button className="cursor-pointer inline-flex items-center hover:opacity-70 transition-opacity flex-shrink-0">
                            <span className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                                <IconChevronRight />
                            </span>
                        </button>
                    )}
                </div>
            </div>
            {isExpanded && (
                <div className="mt-1.5 space-y-1.5 border-l-2 border-border-secondary pl-3.5 ml-2">
                    {steps.map((step, index) => {
                        const isCompleted = step.status === 'completed'
                        const isInProgress = step.status === 'in_progress'

                        return (
                            <div key={index} className="flex items-start gap-2 animate-fade-in">
                                <span className="flex-shrink-0">
                                    <LemonCheckbox checked={isCompleted} disabled size="xsmall" />
                                </span>
                                <span
                                    className={clsx(
                                        'leading-relaxed',
                                        isCompleted && 'text-muted line-through',
                                        isInProgress && 'font-medium'
                                    )}
                                >
                                    {step.description}
                                    {isInProgress && (
                                        <ShimmeringContent>
                                            <span className="text-muted ml-1">(in progress)</span>
                                        </ShimmeringContent>
                                    )}
                                </span>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
