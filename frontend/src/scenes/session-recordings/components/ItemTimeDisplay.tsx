import { useValues } from 'kea'

import { Dayjs } from 'lib/dayjs'
import { getLocalizedDateFormat } from 'lib/utils/dateTimeUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { playerInspectorLogic } from '../player/inspector/playerInspectorLogic'
import { TimestampFormat } from '../player/playerSettingsLogic'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../player/sessionRecordingPlayerLogic'

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
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { durationMs } = useValues(playerInspectorLogic(logicProps))

    // if the recording is less than an hour we can save space by not showing the hours zeroes
    const isLongerThanAnHour = durationMs / 1000 > 3600
    const fixedUnits = isLongerThanAnHour ? 3 : 2

    return (
        <div className={cn('px-2 py-1 text-xs min-w-18 text-center', className)}>
            {timestampFormat !== TimestampFormat.Relative ? (
                (timestampFormat === TimestampFormat.UTC ? timestamp.tz('UTC') : timestamp).format(`${getLocalizedDateFormat()}, HH:mm:ss`)
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
                        colonDelimitedDuration(timeInRecording / 1000, fixedUnits)
                    )}
                </>
            )}
        </div>
    )
}
