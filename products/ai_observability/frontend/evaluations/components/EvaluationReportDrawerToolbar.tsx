import { IconChevronDown, IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import type { ReportDrawerPosition } from '../evaluationReportDrawerLogic'

export interface EvaluationReportDrawerToolbarProps {
    /** Null while the open report is not in the loaded list. */
    position: ReportDrawerPosition | null
    onPrevious: (() => void) | null
    onNext: (() => void) | null
    onCopyLink: () => void
    onGenerate: (() => void) | null
    generateDisabledReason?: string
    onClose: () => void
}

export function EvaluationReportDrawerToolbar({
    position,
    onPrevious,
    onNext,
    onCopyLink,
    onGenerate,
    generateDisabledReason,
    onClose,
}: EvaluationReportDrawerToolbarProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-1 items-center gap-1">
            <LemonButton
                size="small"
                icon={<IconChevronDown className="rotate-180" />}
                tooltip={
                    <>
                        Newer report <KeyboardShortcut p />
                    </>
                }
                aria-label="Newer report"
                data-attr="llma-evaluation-report-drawer-newer"
                onClick={onPrevious ?? undefined}
                disabledReason={onPrevious ? undefined : 'This is the newest report'}
            />
            <LemonButton
                size="small"
                icon={<IconChevronDown />}
                tooltip={
                    <>
                        Older report <KeyboardShortcut n />
                    </>
                }
                aria-label="Older report"
                data-attr="llma-evaluation-report-drawer-older"
                onClick={onNext ?? undefined}
                disabledReason={onNext ? undefined : 'This is the oldest report'}
            />
            {position ? (
                <span className="ml-1 whitespace-nowrap text-xs text-secondary" aria-live="polite">
                    {`${position.index + 1} of ${position.total}${position.more ? '+' : ''}`}
                </span>
            ) : null}
            <div className="ml-auto flex items-center gap-1">
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconLink />}
                    onClick={onCopyLink}
                    data-attr="llma-evaluation-report-drawer-copy-link"
                >
                    Copy link
                </LemonButton>
                {onGenerate || generateDisabledReason ? (
                    <LemonMenu
                        items={[
                            {
                                label: 'Generate a new report',
                                onClick: onGenerate ?? undefined,
                                disabledReason: generateDisabledReason,
                                'data-attr': 'llma-evaluation-report-drawer-generate',
                            },
                        ]}
                    >
                        <LemonButton size="small" icon={<IconEllipsis />} aria-label="More actions" />
                    </LemonMenu>
                ) : null}
                <LemonButton
                    size="small"
                    icon={<IconX />}
                    tooltip={
                        <>
                            Close <KeyboardShortcut escape />
                        </>
                    }
                    aria-label="Close"
                    data-attr="llma-evaluation-report-drawer-close"
                    onClick={onClose}
                />
            </div>
        </div>
    )
}
