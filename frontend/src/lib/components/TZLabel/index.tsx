import './index.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { forwardRef, useCallback, useEffect, useMemo, useState } from 'react'

import { IconClock, IconCopy, IconGear, IconHome, IconLaptop } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonDropdownProps, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconWeb } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { teamLogic } from '../../../scenes/teamLogic'
import { TZLabelLogicProps, tzLabelLogic } from './tzlabelLogic'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY h:mm A'
const BASE_OUTPUT_FORMAT_WITH_SECONDS = 'ddd, MMM D, YYYY h:mm:ss A'

export type TZLabelProps = Omit<LemonDropdownProps, 'overlay' | 'trigger' | 'children'> & {
    time: string | dayjs.Dayjs
    showSeconds?: boolean
    /** Whether to show the absolute or relative timestamp format by default */
    defaultTimestampFormat?: 'absolute' | 'relative'
    /** The key of the logic to use for persisting preferences - defaults to 'global' */
    logicKey?: string
    /** Whether to show a popover on hover - defaults to true */
    noPopover?: boolean
    noStyles?: boolean
    className?: string
    title?: string
    children?: JSX.Element
}

const TZLabelPopoverContent = React.memo(function TZLabelPopoverContent({
    showSeconds,
    time,
    title,
}: Pick<TZLabelProps, 'showSeconds' | 'title'> & { time: dayjs.Dayjs }): JSX.Element {
    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : BASE_OUTPUT_FORMAT_WITH_SECONDS
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)
    const { timestampFormat } = useValues(tzLabelLogic)
    const { setTimestampFormat } = useActions(tzLabelLogic)

    const copyDateTime = (dateTime: dayjs.Dayjs, label: string): void => {
        void copyToClipboard(dateTime.toDate().toISOString(), label)
    }

    useOnMountEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    })

    return (
        <div className={clsx('TZLabelPopover', showSeconds && 'TZLabelPopover--seconds')}>
            <div className="flex justify-between items-center border-b-1 p-1">
                <h4 className="mb-0 px-1">{title || 'Timezone conversion'}</h4>
                <LemonButton icon={<IconGear />} size="xsmall" to={urls.settings('project', 'date-and-time')} />
            </div>
            <div className="space-y-2 p-2">
                <div className="TZLabelPopover__row">
                    <div>
                        <IconLaptop />
                    </div>
                    <div>Your device</div>
                    <div className="text-xs">{shortTimeZone(undefined, time.toDate())}</div>
                    <div className="text-muted text-xs">{time.format(DATE_OUTPUT_FORMAT)}</div>
                    <LemonButton
                        size="xsmall"
                        icon={<IconCopy />}
                        onClick={() => copyDateTime(time, 'your device date')}
                        tooltip="Copy your device date"
                    />
                </div>
                {currentTeam && (
                    <div className="TZLabelPopover__row TZLabelPopover__row--muted">
                        <div>
                            <IconHome />
                        </div>
                        <div>Project</div>
                        <div className="text-xs">{shortTimeZone(currentTeam.timezone, time.toDate())}</div>
                        <div className="text-muted text-xs">
                            {time.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}
                        </div>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            onClick={() => copyDateTime(time.tz(currentTeam.timezone), 'project timezone date')}
                            tooltip="Copy project timezone date"
                        />
                    </div>
                )}
                {currentTeam?.timezone !== 'UTC' && (
                    <div className="TZLabelPopover__row TZLabelPopover__row--muted">
                        <div>
                            <IconWeb />
                        </div>
                        <div />
                        <div className="text-xs">UTC</div>
                        <div className="text-muted text-xs">{time.tz('UTC').format(DATE_OUTPUT_FORMAT)}</div>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            onClick={() => copyDateTime(time.tz('UTC'), 'UTC date')}
                            tooltip="Copy UTC date"
                        />
                    </div>
                )}
            </div>

            <div className="border-t p-2">
                <LemonSelect
                    value={timestampFormat}
                    icon={<IconClock />}
                    onChange={(value) => setTimestampFormat(value)}
                    size="xsmall"
                    fullWidth
                    options={[
                        { value: 'absolute', label: 'Absolute' },
                        { value: 'relative', label: 'Relative' },
                    ]}
                />
            </div>
        </div>
    )
})

/** Return a simple label component with timezone conversion UI. */

const TZLabelRaw = forwardRef<HTMLElement, TZLabelProps>(function TZLabelRaw(
    {
        time,
        showSeconds,
        defaultTimestampFormat = 'relative',
        noPopover = false,
        noStyles = false,
        logicKey,
        title,
        className,
        children,
        ...dropdownProps
    },
    ref
): JSX.Element {
    const logicProps: TZLabelLogicProps = { defaultTimestampFormat, logicKey }
    const { formatting } = useValues(tzLabelLogic(logicProps))
    const parsedTime = useMemo(() => (dayjs.isDayjs(time) ? time : dayjs(time)), [time])

    const format = useCallback(() => {
        if (!formatting) {
            return parsedTime.fromNow()
        }

        return humanFriendlyDetailedTime(parsedTime, formatting.date, formatting.time)
    }, [formatting, parsedTime])

    const [formattedContent, setFormattedContent] = useState(format())

    useEffect(() => {
        // NOTE: This is an optimization to make sure we don't needlessly re-render the component every second.
        const run = (): void => {
            if (format() !== formattedContent) {
                setFormattedContent(format())
            }
        }

        const interval = setInterval(run, 1000)

        // Run immediately and dont wait 1000ms
        run()

        return () => clearInterval(interval)
    }, [parsedTime, format, formattedContent])

    const innerContent = children ?? (
        <span
            className={
                !noStyles
                    ? clsx('whitespace-nowrap align-middle', !noPopover && 'border-dotted border-b', className)
                    : className
            }
            ref={ref}
        >
            {formattedContent}
        </span>
    )

    return (
        <BindLogic logic={tzLabelLogic} props={logicProps}>
            {!noPopover ? (
                <LemonDropdown
                    placement="top"
                    showArrow
                    {...dropdownProps}
                    trigger="hover"
                    closeOnClickInside={false}
                    overlay={<TZLabelPopoverContent time={parsedTime} showSeconds={showSeconds} title={title} />}
                >
                    {innerContent}
                </LemonDropdown>
            ) : (
                innerContent
            )}
        </BindLogic>
    )
})
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
