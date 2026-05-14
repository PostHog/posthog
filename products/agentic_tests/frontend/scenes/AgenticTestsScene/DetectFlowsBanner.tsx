import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { detectFlowsLogic } from './detectFlowsLogic'

const STEPS = [{ label: 'Setting up' }, { label: 'Analyzing product' }, { label: 'Done' }] as const

export function DetectFlowsBanner(): JSX.Element | null {
    const { bannerVisible, step, proposedCount, isTerminal, isFailed } = useValues(detectFlowsLogic)
    const { openLogsModal, dismissBanner } = useActions(detectFlowsLogic)

    if (!bannerVisible) {
        return null
    }

    const stepThreeLabel = isFailed
        ? 'Failed'
        : proposedCount !== null
          ? `Done — ${proposedCount} flow${proposedCount !== 1 ? 's' : ''} proposed`
          : 'Done'

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-10 flex gap-1">
            <LemonButton type="secondary" size="large" onClick={openLogsModal}>
                <div className="flex items-center gap-3">
                    {STEPS.map((s, i) => {
                        const stepNum = (i + 1) as 1 | 2 | 3
                        const completed = step > stepNum
                        const active = step === stepNum
                        const isFailedStep = active && isFailed
                        const label = stepNum === 3 ? stepThreeLabel : s.label
                        return (
                            <div key={i} className="flex items-center gap-1.5">
                                {i > 0 && <div className="w-3 h-px bg-border" />}
                                {active && !isTerminal ? (
                                    <Spinner className="text-primary" />
                                ) : isFailedStep ? (
                                    <IconWarning className="text-danger w-4 h-4" />
                                ) : completed ? (
                                    <IconCheck className="text-success w-4 h-4" />
                                ) : (
                                    <span className="text-muted text-xs">{stepNum}</span>
                                )}
                                <span
                                    className={
                                        isFailedStep
                                            ? 'font-semibold text-danger'
                                            : active
                                              ? 'font-semibold'
                                              : completed
                                                ? 'text-success'
                                                : 'text-muted'
                                    }
                                >
                                    {label}
                                </span>
                            </div>
                        )
                    })}
                </div>
            </LemonButton>
            {isTerminal && (
                <LemonButton type="secondary" onClick={dismissBanner} tooltip="Dismiss">
                    Dismiss
                </LemonButton>
            )}
        </div>
    )
}
