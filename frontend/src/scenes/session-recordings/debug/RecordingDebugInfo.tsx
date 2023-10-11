import clsx from 'clsx'
import { useValues } from 'kea'
import { IconInfo } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SessionRecordingType } from '~/types'

export function RecordingDebugInfo({
    recording,
    className,
}: {
    recording: SessionRecordingType
    className?: string
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const debugMode = !!featureFlags[FEATURE_FLAGS.RECORDING_DEBUGGING]

    if (!debugMode) {
        return null
    }

    return (
        <Tooltip
            title={
                <ul>
                    <li>
                        ID: <b>{recording.id}</b>
                    </li>
                    <li>
                        Storage: <b>{recording.storage}</b>
                    </li>
                </ul>
            }
        >
            <IconInfo className={clsx('text-sm', className)} />
        </Tooltip>
    )
}
