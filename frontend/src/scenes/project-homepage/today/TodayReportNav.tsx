import { useActions, useMountedLogic, useValues } from 'kea'

import { IconArrowLeft, IconChevronDown } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { type HotkeyInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todayLogic } from './todayLogic'
import { todayReportLogic } from './todayReportLogic'
import { todayReportQueueLogic } from './todayReportQueueLogic'
import { isPlainClick } from './todayViewTransition'

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
    )
}

function overlayOpen(): boolean {
    return Array.from(
        document.querySelectorAll('[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]')
    ).some((element) => !element.closest('aside, [inert], [aria-hidden="true"]'))
}

function reportShortcut(run: () => void): HotkeyInterface {
    return {
        action: (event) => {
            if (!isTyping(event.target) && !overlayOpen()) {
                run()
            }
        },
    }
}

function TodayReportPrefetch({ reportId }: { reportId: string }): null {
    useMountedLogic(todayReportLogic({ reportId }))
    return null
}

function StepButton({
    step,
    label,
    shortcut,
    disabled,
}: {
    step: 1 | -1
    label: string
    shortcut: string
    disabled: boolean
}): JSX.Element {
    const { openAdjacentReport } = useActions(todayReportQueueLogic)
    const { moreReportsLoading } = useValues(todayLogic)
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label={label}
                        disabled={disabled || moreReportsLoading}
                        onClick={() => openAdjacentReport(step)}
                        data-attr={step === 1 ? 'today-report-next' : 'today-report-previous'}
                    />
                }
            >
                <IconChevronDown className={step === -1 ? 'size-4 rotate-180' : 'size-4'} />
            </TooltipTrigger>
            <TooltipContent>{`${label} (${shortcut})`}</TooltipContent>
        </Tooltip>
    )
}

export function TodayReportNav(): JSX.Element {
    const { reportPosition, reportQueueIds, adjacentReportIds, atQueueEnd, restInInbox } =
        useValues(todayReportQueueLogic)
    const { openAdjacentReport, leaveReport } = useActions(todayReportQueueLogic)

    useKeyboardHotkeys(
        {
            escape: reportShortcut(leaveReport),
            j: reportShortcut(() => openAdjacentReport(1)),
            k: reportShortcut(() => openAdjacentReport(-1)),
        },
        [leaveReport, openAdjacentReport]
    )

    return (
        <nav className="TodayReportNav" aria-label="Reports">
            {adjacentReportIds.map((id) => (
                <TodayReportPrefetch key={id} reportId={id} />
            ))}
            <LinkPrimitive
                to={urls.projectHomepage()}
                className="TodayReportNav__back"
                onClick={(event) => {
                    if (isPlainClick(event)) {
                        event.preventDefault()
                        leaveReport()
                    }
                }}
                data-attr="today-report-back"
            >
                <IconArrowLeft className="size-3.5" />
                <span>Home</span>
            </LinkPrimitive>
            {reportPosition !== null && (
                <span className="TodayReportNav__steps">
                    <span className="TodayReportNav__count" translate="no">
                        {`${reportPosition} of ${reportQueueIds.length}`}
                    </span>
                    <StepButton step={-1} label="Previous report" shortcut="K" disabled={reportPosition <= 1} />
                    <StepButton
                        step={1}
                        label={restInInbox ? 'Open the Inbox for the rest' : 'Next report'}
                        shortcut="J"
                        disabled={atQueueEnd && !restInInbox}
                    />
                </span>
            )}
        </nav>
    )
}
