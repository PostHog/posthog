import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'

import { DataQualityScheduleLogicProps, dataQualityScheduleLogic } from './dataQualityScheduleLogic'
import { DataQualityScheduleIntervalEnumApi } from './generated/api.schemas'
import { QuillCheckCallout } from './QuillCheckCallout'

const NEXT_RUN_LABEL_REFRESH_INTERVAL_MS = 1_000

const INTERVAL_OPTIONS: { value: DataQualityScheduleIntervalEnumApi; label: string }[] = [
    { value: DataQualityScheduleIntervalEnumApi['1hour'], label: 'Every hour' },
    { value: DataQualityScheduleIntervalEnumApi['6hour'], label: 'Every 6 hours' },
    { value: DataQualityScheduleIntervalEnumApi['12hour'], label: 'Every 12 hours' },
    { value: DataQualityScheduleIntervalEnumApi['24hour'], label: 'Daily' },
    { value: DataQualityScheduleIntervalEnumApi['7day'], label: 'Weekly' },
]

function NextRunTime({ nextRunAt }: { nextRunAt: string }): JSX.Element {
    usePeriodicRerender(NEXT_RUN_LABEL_REFRESH_INTERVAL_MS)

    if (dayjs(nextRunAt).valueOf() <= Date.now()) {
        return (
            <Tooltip>
                <TooltipTrigger render={<span />}>due now</TooltipTrigger>
                <TooltipContent>Refreshing the next scheduled time.</TooltipContent>
            </Tooltip>
        )
    }

    return <TZLabel time={nextRunAt} />
}

export function QuillDataQualitySchedule(props: DataQualityScheduleLogicProps): JSX.Element {
    const logic = dataQualityScheduleLogic(props)
    const { schedule, scheduleLoading, scheduleError } = useValues(logic)
    const { loadSchedule, updateSchedule } = useActions(logic)
    const switchId = useId()

    if (!schedule) {
        return scheduleError ? (
            <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: loadSchedule }}>
                Could not load the check schedule. Try again.
            </QuillCheckCallout>
        ) : (
            <Spinner />
        )
    }

    const uncertain = !!scheduleError?.uncertain
    const intervalDisabledReason = scheduleLoading
        ? 'Saving schedule'
        : uncertain
          ? 'Reload the schedule to try again'
          : undefined

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-2">
                    <Switch
                        id={switchId}
                        checked={schedule.enabled}
                        onCheckedChange={(enabled: boolean) => updateSchedule({ enabled })}
                        disabledReason={intervalDisabledReason}
                        data-attr="data-quality-schedule-enabled"
                    />
                    <Label htmlFor={switchId}>Run automatically</Label>
                </div>
                <Select
                    items={INTERVAL_OPTIONS}
                    value={schedule.interval}
                    onValueChange={(interval) => {
                        if (interval) {
                            updateSchedule({ interval: interval as DataQualityScheduleIntervalEnumApi })
                        }
                    }}
                    disabled={!!intervalDisabledReason}
                >
                    <SelectTrigger aria-label="How often checks run" data-attr="data-quality-schedule-interval">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {INTERVAL_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                {scheduleLoading ? (
                    <Spinner />
                ) : (
                    schedule.enabled &&
                    schedule.next_run_at && (
                        <Text size="xs" variant="muted" render={<span />}>
                            Next run <NextRunTime nextRunAt={schedule.next_run_at} />
                        </Text>
                    )
                )}
            </div>
            {scheduleError &&
                (scheduleError.uncertain ? (
                    <QuillCheckCallout
                        tone="destructive"
                        action={{ label: 'Reload', onClick: loadSchedule, loading: scheduleLoading }}
                    >
                        Could not confirm the schedule update. Reload it before trying again.
                    </QuillCheckCallout>
                ) : (
                    <QuillCheckCallout tone="destructive">{scheduleError.message}</QuillCheckCallout>
                ))}
        </div>
    )
}
