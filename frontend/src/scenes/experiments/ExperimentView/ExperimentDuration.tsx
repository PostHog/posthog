import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'
import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'

import { confirmChangeExperimentDate } from '../experimentActions'
import { experimentLogic } from '../experimentLogic'

interface DateButtonProps {
    date: string | null | undefined
    type: 'start' | 'end'
    timezone: string
    onChange: (date: string) => void
}

const DateButton = ({ date, type, timezone, onChange }: DateButtonProps): JSX.Element => {
    const containerWidth = 'w-44'
    const [isOpen, setIsOpen] = useState(false)

    return (
        <div className={containerWidth}>
            <Popover
                actionable
                onClickOutside={() => setIsOpen(false)}
                visible={isOpen}
                overlay={
                    <LemonCalendarSelect
                        value={date ? dayjs(date).tz(timezone) : null}
                        onChange={(value) => {
                            // Changing either date reshapes the analysis window, so confirm before applying.
                            confirmChangeExperimentDate({
                                type,
                                newDate: value.toISOString(),
                                timezone,
                                onConfirm: () => onChange(value.toISOString()),
                            })
                            setIsOpen(false)
                        }}
                        onClose={() => setIsOpen(false)}
                        granularity="minute"
                        selectionPeriod={type === 'start' ? 'past' : undefined}
                    />
                }
            >
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => setIsOpen(true)}
                    fullWidth
                    disabledReason={
                        !date && type === 'start'
                            ? 'No start date'
                            : !date && type === 'end'
                              ? 'Experiment is still running'
                              : undefined
                    }
                >
                    {date ? (
                        <TZLabel
                            time={date}
                            formatDate="MMM DD, YYYY"
                            formatTime="hh:mm A"
                            displayTimezone={timezone}
                            showPopover={true}
                            noStyles={true}
                        />
                    ) : type === 'end' ? (
                        'Present'
                    ) : (
                        'No date'
                    )}
                </LemonButton>
            </Popover>
        </div>
    )
}

export const ExperimentDuration = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)
    const { timezone } = useValues(teamLogic)

    const { start_date, end_date } = experiment
    const tzAbbreviation = shortTimeZone(timezone) ?? timezone

    return (
        <div>
            <Label intent="menu">Duration ({tzAbbreviation}, project timezone)</Label>
            <div className="flex gap-2 items-center">
                <div className="flex items-center gap-2">
                    <DateButton
                        date={start_date}
                        type="start"
                        timezone={timezone}
                        onChange={changeExperimentStartDate}
                    />
                    <IconArrowRight className="text-base" />
                    <DateButton date={end_date} type="end" timezone={timezone} onChange={changeExperimentEndDate} />
                </div>
            </div>
        </div>
    )
}
