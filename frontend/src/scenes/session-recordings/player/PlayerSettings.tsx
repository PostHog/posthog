import { IconEllipsis, IconFastForward } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { playerSettingsLogic } from './playerSettingsLogic'
import { PLAYBACK_SPEEDS } from './sessionRecordingPlayerLogic'

export const PlayerSettings = (): JSX.Element => {
    const { speed, skipInactivitySetting, showMouseTail } = useValues(playerSettingsLogic)
    const { setSpeed, setSkipInactivitySetting, setShowMouseTail } = useActions(playerSettingsLogic)

    // <LemonMenu
    //                         data-attr="session-recording-speed-select"
    //                         items={PLAYBACK_SPEEDS.map((speedToggle) => ({
    //                             label: `${speedToggle}x`,
    //                             onClick: () => setSpeed(speedToggle),
    //                         }))}
    //                     >
    //                         <LemonButton size="small" tooltip="Playback speed" sideIcon={null}>
    //                             {speed}x
    //                         </LemonButton>
    //                     </LemonMenu>

    return (
        <LemonMenu
            closeOnClickInside={false}
            items={[
                {
                    custom: true,
                    label: () => (
                        <LemonSwitch
                            className="px-2 py-1"
                            checked={showMouseTail}
                            onChange={setShowMouseTail}
                            label="Show mouse tail"
                            fullWidth
                        />
                    ),
                },
                {
                    custom: true,
                    label: () => (
                        <LemonSwitch
                            handleContent={
                                <IconFastForward
                                    className={clsx(
                                        'p-0.5',
                                        skipInactivitySetting ? 'text-primary-3000' : 'text-border-bold'
                                    )}
                                />
                            }
                            fullWidth
                            data-attr="skip-inactivity"
                            className="px-2 py-1"
                            checked={skipInactivitySetting}
                            onChange={setSkipInactivitySetting}
                            label="Skip inactivity"
                        />
                    ),
                },
                {
                    label: `Playback speed (${speed}x)`,
                    items: PLAYBACK_SPEEDS.map((speedToggle) => ({
                        label: `${speedToggle}x`,
                        onClick: () => setSpeed(speedToggle),
                        active: speedToggle === speed,
                    })),
                },
            ]}
        >
            <div className="pl-2">
                <LemonButton size="small" icon={<IconEllipsis />} />
            </div>
        </LemonMenu>
    )
}
