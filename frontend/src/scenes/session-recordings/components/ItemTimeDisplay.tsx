import { useValues } from 'kea'

import { Dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { formatLocalizedDate } from 'lib/utils/dateTimeUtils'

import { TimestampFormat } from '../player/playerSettingsLogic'
import { playerSettingsLogic } from '../player/playerSettingsLogic'

export function ItemTimeDisplay({
    timestamp,
    timeInRecording,
    className,
}: {
    timestamp: Dayjs
    timeInRecording: number
    className?: string
}): JSX.Element {
    const { timestampFormat } = useValues(playerSettingsLogic)

    return (
        <div className={cn('px-2 py-1 text-xs min-w-18 text-center', className)}>
            {timestampFormat !== TimestampFormat.Relative ? (
                (timestampFormat === TimestampFormat.UTC ? timestamp.tz('UTC') : timestamp).format(
                    `${formatLocalizedDate()}, HH:mm:ss`
                )
            ) : (
                <>
                    {timeInRecording < 0 ? (
                        <Tooltip
                            title="This event occurred before the recording started, likely as the page was loading."
                            placement="left"
                        >
                            <span className="text-secondary">load</span>
                        </Tooltip>
                    ) : (
                        colonDelimitedDuration(timeInRecording / 1000, null)
                    )}
                </>
            )}
        </div>
    )
}
