import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconArrowRight, IconCalculator, IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'
import { humanFriendlyDetailedTime, humanFriendlyNumber } from 'lib/utils'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

interface DateButtonProps {
    date: string | null | undefined
    type: 'start' | 'end'
    onChange: (date: string) => void
}

const DateButton = ({ date, type, onChange }: DateButtonProps): JSX.Element => {
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
                        value={date ? dayjs(date) : null}
                        onChange={(value) => {
                            onChange(value.toISOString())
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
                    {date
                        ? humanFriendlyDetailedTime(date, 'MMM DD, YYYY', 'hh:mm A')
                        : type === 'end'
                          ? 'Present'
                          : 'No date'}
                </LemonButton>
            </Popover>
        </div>
    )
}

export const ExperimentDuration = (): JSX.Element => {
    const { experiment, actualRunningTime } = useValues(experimentLogic)
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)
    const { openCalculateRunningTimeModal } = useActions(modalsLogic)

    const { start_date, end_date } = experiment
    const [progressPopoverVisible, setProgressPopoverVisible] = useState(false)
    const hideTimeoutRef = useRef<NodeJS.Timeout | null>(null)

    const recommendedSampleSize = experiment.parameters.recommended_sample_size
    const minimumDetectableEffect = experiment.parameters.minimum_detectable_effect
    const recommendedRunningTime = experiment.parameters.recommended_running_time

    const showPopover = (): void => {
        if (hideTimeoutRef.current) {
            clearTimeout(hideTimeoutRef.current)
            hideTimeoutRef.current = null
        }
        setProgressPopoverVisible(true)
    }

    const hidePopover = (): void => {
        hideTimeoutRef.current = setTimeout(() => {
            setProgressPopoverVisible(false)
            hideTimeoutRef.current = null
        }, 100) // 100ms delay - enough time to move to popover
    }

    return (
        <div>
            <Label intent="menu">Duration</Label>
            <div className="flex gap-2 items-center">
                <div className="flex items-center gap-2">
                    <DateButton date={start_date} type="start" onChange={changeExperimentStartDate} />
                    <IconArrowRight className="text-base" />
                    <DateButton date={end_date} type="end" onChange={changeExperimentEndDate} />
                </div>
                <Popover
                    visible={progressPopoverVisible}
                    onMouseEnterInside={showPopover}
                    onMouseLeaveInside={hidePopover}
                    overlay={
                        <div className="p-2">
                            {!recommendedSampleSize || !recommendedRunningTime ? (
                                <div className="flex justify-center items-center h-full">
                                    <div className="text-center">
                                        <IconCalculator className="text-3xl mb-2 text-tertiary" />
                                        <div className="text-md font-semibold leading-tight mb-3">
                                            No running time yet
                                        </div>
                                        <div className="flex justify-center">
                                            <LemonButton
                                                icon={<IconPencil fontSize="12" />}
                                                size="xsmall"
                                                className="flex items-center gap-2"
                                                type="secondary"
                                                onClick={() => openCalculateRunningTimeModal()}
                                            >
                                                Calculate running time
                                            </LemonButton>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <>
                                    <LemonProgress
                                        className="w-full border"
                                        bgColor="var(--color-bg-table)"
                                        size="medium"
                                        percent={(actualRunningTime / recommendedRunningTime) * 100}
                                    />
                                    <div className="text-center mt-2 mb-4 text-xs text-muted">
                                        {actualRunningTime} of {humanFriendlyNumber(recommendedRunningTime, 0)} days
                                        completed ({Math.round((actualRunningTime / recommendedRunningTime) * 100)}%)
                                    </div>

                                    <div className="space-y-3">
                                        <div>
                                            <div className="card-secondary mb-1">Recommended sample size</div>
                                            <div className="text-sm font-semibold">
                                                {humanFriendlyNumber(recommendedSampleSize, 0)} users
                                            </div>
                                        </div>
                                        <div>
                                            <div className="card-secondary mb-1">Estimated running time</div>
                                            <div className="text-sm font-semibold">
                                                {humanFriendlyNumber(recommendedRunningTime, 0)} days
                                            </div>
                                        </div>
                                        <div>
                                            <div className="card-secondary mb-1">Minimum detectable effect</div>
                                            <div className="text-sm font-semibold">{minimumDetectableEffect}%</div>
                                        </div>
                                        <LemonButton
                                            size="xsmall"
                                            className="flex items-center gap-2 mt-4"
                                            type="secondary"
                                            onClick={() => openCalculateRunningTimeModal()}
                                        >
                                            Recalculate
                                        </LemonButton>
                                    </div>
                                </>
                            )}
                        </div>
                    }
                >
                    <div onMouseEnter={showPopover} onMouseLeave={hidePopover} style={{ color: 'var(--brand-blue)' }}>
                        <LemonProgressCircle
                            progress={
                                recommendedRunningTime ? Math.min(actualRunningTime / recommendedRunningTime, 1) : 0
                            }
                            size={22}
                        />
                    </div>
                </Popover>
            </div>
        </div>
    )
}
