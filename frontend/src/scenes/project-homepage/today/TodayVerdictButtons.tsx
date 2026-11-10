import { useActions } from 'kea'

import { IconCheckCircle, IconHide } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { isSampleReportId } from './todaySampleReports'
import { type TodayReportVerdict, type TodayReportVerdictTarget, todayVerdictLogic } from './todayVerdictLogic'

const VERDICT_BUTTONS: { verdict: TodayReportVerdict; label: string; icon: JSX.Element }[] = [
    { verdict: 'resolve', label: 'Resolve', icon: <IconCheckCircle className="size-3.5" /> },
    { verdict: 'dismiss', label: 'Dismiss', icon: <IconHide className="size-3.5" /> },
]

export function TodayVerdictButtons({
    target,
    labelled = false,
}: {
    target: TodayReportVerdictTarget
    labelled?: boolean
}): JSX.Element {
    const { requestReportVerdict } = useActions(todayVerdictLogic)
    const disabled = isSampleReportId(target.reportId)
    return (
        <>
            {VERDICT_BUTTONS.map(({ verdict, label, icon }) => {
                const onClick = (): void => requestReportVerdict(target, verdict, 'briefing')
                return labelled ? (
                    <Button
                        key={verdict}
                        variant="link-muted"
                        size="sm"
                        disabled={disabled}
                        onClick={onClick}
                        data-attr={`today-list-${verdict}`}
                    >
                        {icon}
                        {label}
                    </Button>
                ) : (
                    <Tooltip key={verdict}>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="link-muted"
                                    size="icon-sm"
                                    aria-label={label}
                                    disabled={disabled}
                                    onClick={onClick}
                                    data-attr={`today-list-${verdict}`}
                                />
                            }
                        >
                            {icon}
                        </TooltipTrigger>
                        <TooltipContent side="bottom">{label}</TooltipContent>
                    </Tooltip>
                )
            })}
        </>
    )
}
