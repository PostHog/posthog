import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { detectFlowsLogic } from './detectFlowsLogic'

const STEPS = [
    { active: 'Setting up sandbox', done: 'Sandbox set up' },
    { active: 'Analyzing product', done: 'Product analyzed' },
] as const

export function DetectFlowsBanner(): JSX.Element | null {
    const { bannerVisible, step, proposedCount, isTerminal, isFailed, hasLogs } = useValues(detectFlowsLogic)
    const { openLogsModal, dismissBanner } = useActions(detectFlowsLogic)

    if (!bannerVisible) {
        return null
    }

    const doneLabel = isFailed
        ? 'Failed'
        : proposedCount !== null && proposedCount > 0
          ? `${proposedCount} test${proposedCount !== 1 ? 's' : ''} proposed`
          : isTerminal
            ? 'Tests proposed'
            : 'Proposing tests'

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-10 flex gap-2">
            <LemonButton
                type="secondary"
                onClick={openLogsModal}
                className="bg-bg-light"
                disabledReason={isTerminal && !hasLogs ? 'Logs are no longer available' : undefined}
            >
                <div className="flex items-center gap-3">
                    <span className="font-semibold text-xxs uppercase tracking-wider">Key flow detection</span>
                    <div className="w-px h-4 bg-border" />
                    {STEPS.map((s, i) => {
                        const stepNum = (i + 1) as 1 | 2
                        const completed = step > stepNum
                        const active = step === stepNum
                        return (
                            <div key={i} className="flex items-center gap-1.5">
                                {i > 0 && <div className="w-3 h-px bg-border" />}
                                {active ? (
                                    <Spinner className="text-primary" />
                                ) : completed ? (
                                    <IconCheck className="text-success w-4 h-4" />
                                ) : (
                                    <span className="text-muted text-xs">{stepNum}</span>
                                )}
                                <span className={completed ? 'text-success' : active ? 'font-semibold' : 'text-muted'}>
                                    {completed ? s.done : s.active}
                                </span>
                            </div>
                        )
                    })}
                    <div className="flex items-center gap-1.5">
                        <div className="w-3 h-px bg-border" />
                        {isTerminal ? (
                            isFailed ? (
                                <IconWarning className="text-danger w-4 h-4" />
                            ) : (
                                <IconCheck className="text-success w-4 h-4" />
                            )
                        ) : step === 3 ? (
                            <Spinner className="text-primary" />
                        ) : (
                            <span className="text-muted text-xs">3</span>
                        )}
                        <span
                            className={
                                isFailed
                                    ? 'font-semibold text-danger'
                                    : isTerminal
                                      ? 'text-success'
                                      : step === 3
                                        ? 'font-semibold'
                                        : 'text-muted'
                            }
                        >
                            {doneLabel}
                        </span>
                    </div>
                </div>
            </LemonButton>
            {isTerminal && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={dismissBanner}
                    tooltip="Dismiss"
                    icon={<IconX />}
                    className="bg-bg-light"
                />
            )}
        </div>
    )
}
