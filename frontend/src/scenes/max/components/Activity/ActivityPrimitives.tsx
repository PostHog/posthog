import clsx from 'clsx'
import React, { useLayoutEffect, useState } from 'react'

import { IconCheck, IconChevronRight, IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { MarkdownMessage } from '../../MarkdownMessage'

export type ActivityStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export function ShimmeringContent({ children }: { children: React.ReactNode }): JSX.Element {
    const isTextContent = typeof children === 'string'

    if (isTextContent) {
        return (
            <span
                className="bg-clip-text text-transparent"
                style={{
                    backgroundImage:
                        'linear-gradient(in oklch 90deg, var(--text-3000), var(--muted-3000), var(--trace-3000), var(--muted-3000), var(--text-3000))',
                    backgroundSize: '200% 100%',
                    animation: 'shimmer 3s linear infinite',
                }}
            >
                {children}
            </span>
        )
    }

    return (
        <span
            className="inline-flex min-w-0 max-w-full"
            style={{
                animation: 'shimmer-opacity 3s linear infinite',
            }}
        >
            {children}
        </span>
    )
}

function activitySubstepText(content: string, isInProgress: boolean): string {
    if (content.at(0) === '[' && content.at(-1) === ')') {
        // Skip ... for web search `updates`, where each is a Markdown-formatted link to a search result.
        return content
    }
    if (!content.endsWith('...') && !content.endsWith('\u2026') && !content.endsWith('.') && isInProgress) {
        return content + '...'
    } else if ((content.endsWith('...') || content.endsWith('\u2026')) && !isInProgress) {
        return content.replace(/\u2026/g, '').replace(/[.]/g, '')
    }
    return content
}

export function ActivityStatusIcon({
    status,
    showCompletionIcon = true,
    showProgressIcon = false,
    failedIcon,
}: {
    status: ActivityStatus
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: React.ReactNode
}): JSX.Element | null {
    if ((status === 'pending' || status === 'in_progress') && showProgressIcon) {
        return <Spinner className="size-3" />
    }
    if (status === 'completed' && showCompletionIcon) {
        return <IconCheck className="text-success size-3" />
    }
    if (status === 'failed' && showCompletionIcon) {
        return failedIcon ? <>{failedIcon}</> : <IconX className="text-danger size-3" />
    }
    return null
}

export function ActivityHeader({
    title,
    status,
    icon,
    animate = true,
    hasDetails,
    isDetailsExpanded,
    onToggleDetails,
    showCompletionIcon = true,
    showProgressIcon = false,
    failedIcon,
}: {
    title: React.ReactNode
    status: ActivityStatus
    icon?: React.ReactNode
    animate?: boolean
    hasDetails: boolean
    isDetailsExpanded: boolean
    onToggleDetails: () => void
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: React.ReactNode
}): JSX.Element {
    const isPending = status === 'pending'
    const isInProgress = status === 'in_progress'
    const isFailed = status === 'failed'

    return (
        <div
            className={clsx(
                'transition-all duration-500 flex select-none min-w-0',
                (isPending || isFailed) && 'text-muted',
                !isInProgress && !isPending && !isFailed && 'text-default',
                hasDetails ? 'cursor-pointer' : 'cursor-default'
            )}
            onClick={hasDetails ? onToggleDetails : undefined}
            aria-label={hasDetails ? (isDetailsExpanded ? 'Collapse history' : 'Expand history') : undefined}
        >
            {icon && (
                <div className="flex items-center justify-center size-5">
                    {isInProgress && animate ? (
                        <ShimmeringContent>{icon}</ShimmeringContent>
                    ) : (
                        <span className={clsx('inline-flex', isInProgress && 'text-muted')}>{icon}</span>
                    )}
                </div>
            )}
            <div className="flex items-center gap-1 flex-1 min-w-0 h-full">
                <div className="min-w-0">
                    {isInProgress && animate ? (
                        <ShimmeringContent>{title}</ShimmeringContent>
                    ) : (
                        <span className={clsx('inline-flex', isInProgress && 'text-muted')}>{title}</span>
                    )}
                </div>
                {hasDetails && (
                    <div className="relative shrink-0 flex flex-col items-start justify-center h-full">
                        <button className="inline-flex items-center hover:opacity-70 transition-opacity shrink-0 cursor-pointer">
                            <span className={clsx('transform transition-transform', isDetailsExpanded && 'rotate-90')}>
                                <IconChevronRight />
                            </span>
                        </button>
                    </div>
                )}
                <ActivityStatusIcon
                    status={status}
                    showCompletionIcon={showCompletionIcon}
                    showProgressIcon={showProgressIcon}
                    failedIcon={failedIcon}
                />
            </div>
        </div>
    )
}

export function ActivitySubsteps({
    id,
    substeps,
    status,
}: {
    id: string
    substeps: string[]
    status: ActivityStatus
}): JSX.Element {
    const isCompleted = status === 'completed'
    const isFailed = status === 'failed'

    return (
        <>
            {substeps.map((substep, substepIndex) => {
                const isCurrentSubstep = substepIndex === substeps.length - 1
                const isCompletedSubstep = substepIndex < substeps.length - 1 || isCompleted

                return (
                    <div key={substepIndex} className="animate-fade-in">
                        <MarkdownMessage
                            id={id}
                            className={clsx(
                                'leading-relaxed',
                                isFailed && 'text-danger',
                                !isFailed && isCompletedSubstep && 'text-muted',
                                !isFailed && isCurrentSubstep && !isCompleted && 'text-secondary'
                            )}
                            content={activitySubstepText(substep ?? '', status === 'in_progress')}
                        />
                    </div>
                )
            })}
        </>
    )
}

export function ActivityDetails({ children, hasIcon }: { children: React.ReactNode; hasIcon: boolean }): JSX.Element {
    return (
        <div className={clsx('space-y-1 border-l-2 border-border-secondary', hasIcon && 'pl-3.5 ml-[calc(0.775rem)]')}>
            {children}
        </div>
    )
}

export function ActivityToggleSection({
    title,
    summary,
    tooltip,
    children,
}: {
    title: React.ReactNode
    summary?: React.ReactNode
    tooltip?: string
    children: React.ReactNode
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className="flex flex-col gap-1">
            <LemonButton
                size="xxsmall"
                type="tertiary"
                onClick={(e) => {
                    e.stopPropagation()
                    setIsExpanded(!isExpanded)
                }}
                tooltip={tooltip}
                tooltipPlacement="top-start"
                className="w-fit"
            >
                <span className="flex items-center gap-1">
                    <b>{title}</b>
                    {summary && <span className="text-secondary">{summary}</span>}
                    <span className={clsx('transform transition-transform', isExpanded && 'rotate-90')}>
                        <IconChevronRight />
                    </span>
                </span>
            </LemonButton>
            {isExpanded && children}
        </div>
    )
}

export function Activity({
    id,
    title,
    status,
    icon,
    animate = true,
    showCompletionIcon = true,
    showProgressIcon = false,
    failedIcon,
    substeps = [],
    details = null,
    children = null,
}: {
    id: string
    title: React.ReactNode
    status: ActivityStatus
    icon?: React.ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: React.ReactNode
    substeps?: string[]
    details?: React.ReactNode
    children?: React.ReactNode
}): JSX.Element {
    const hasDetails = substeps.length > 0 || !!details
    const shouldExpandDetails = hasDetails && status !== 'completed' && status !== 'failed'
    const [isDetailsExpanded, setIsDetailsExpanded] = useState(shouldExpandDetails)

    useLayoutEffect(() => {
        setIsDetailsExpanded(shouldExpandDetails)
    }, [shouldExpandDetails])

    return (
        <div className="flex flex-col rounded transition-all duration-500 w-full min-w-0 gap-1 text-xs">
            <ActivityHeader
                title={title}
                status={status}
                icon={icon}
                animate={animate}
                hasDetails={hasDetails}
                isDetailsExpanded={isDetailsExpanded}
                onToggleDetails={() => setIsDetailsExpanded(!isDetailsExpanded)}
                showCompletionIcon={showCompletionIcon}
                showProgressIcon={showProgressIcon}
                failedIcon={failedIcon}
            />
            {children}
            {isDetailsExpanded && hasDetails && (
                <ActivityDetails hasIcon={!!icon}>
                    {substeps.length > 0 && <ActivitySubsteps id={id} substeps={substeps} status={status} />}
                    {details}
                </ActivityDetails>
            )}
        </div>
    )
}
