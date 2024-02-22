import { LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconPause, IconPlay } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DurationTypeSelect } from 'scenes/session-recordings/filters/DurationTypeSelect'

import { playerSettingsLogic } from '../player/playerSettingsLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { autoplayDirection, durationTypeToShow, hideViewedRecordings } = useValues(playerSettingsLogic)
    const { toggleAutoplayDirection, setDurationTypeToShow, setHideViewedRecordings } = useActions(playerSettingsLogic)

    return (
        <div className="relative flex flex-col gap-2 p-3 bg-side border-b">
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Autoplay</span>
                <Tooltip
                    title={
                        <div className="text-center">
                            Autoplay next recording
                            <br />({!autoplayDirection ? 'disabled' : autoplayDirection})
                        </div>
                    }
                    placement="bottom"
                >
                    <LemonSwitch
                        aria-label="Autoplay next recording"
                        checked={!!autoplayDirection}
                        onChange={toggleAutoplayDirection}
                        handleContent={
                            <span
                                className={clsx(
                                    'transition-all flex items-center',
                                    !autoplayDirection && 'text-border text-sm',
                                    !!autoplayDirection && 'text-white text-xs pl-px',
                                    autoplayDirection === 'newer' && 'rotate-180'
                                )}
                            >
                                {autoplayDirection ? <IconPlay /> : <IconPause />}
                            </span>
                        }
                    />
                </Tooltip>
            </div>
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Hide viewed</span>
                <LemonSwitch
                    aria-label="Autoplay next recording"
                    checked={hideViewedRecordings}
                    onChange={() => setHideViewedRecordings(!hideViewedRecordings)}
                />
            </div>
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Show</span>
                <DurationTypeSelect
                    value={durationTypeToShow}
                    onChange={(value) => setDurationTypeToShow(value)}
                    onChangeEventDescription="session recording list duration type to show selected"
                />
            </div>
        </div>
    )
}
