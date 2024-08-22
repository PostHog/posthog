import { IconEllipsis, IconFastForward } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { playerSettingsLogic } from './playerSettingsLogic'
import { PLAYBACK_SPEEDS } from './sessionRecordingPlayerLogic'

export const PlayerSettings = (): JSX.Element => {
    const { speed, autoplayDirection, skipInactivitySetting, showMouseTail } = useValues(playerSettingsLogic)
    const { setSpeed, setAutoplayDirection, setSkipInactivitySetting, setShowMouseTail } =
        useActions(playerSettingsLogic)

    return (
        <LemonMenu
            closeOnClickInside={false}
            items={[
                {
                    custom: true,
                    label: () => (
                        <div className="flex flex-row items-center justify-between space-x-2 p-1 min-w-64">
                            <span className="text-black font-medium">Autoplay</span>

                            <LemonSelect
                                tooltip={
                                    <div className="text-center">
                                        Autoplay next recording
                                        <br />({!autoplayDirection ? 'off' : autoplayDirection})
                                    </div>
                                }
                                value={autoplayDirection}
                                aria-label="Autoplay next recording"
                                onChange={setAutoplayDirection}
                                dropdownMatchSelectWidth={false}
                                options={[
                                    { value: null, label: 'off' },
                                    { value: 'newer', label: 'newer recordings' },
                                    { value: 'older', label: 'older recordings' },
                                ]}
                                size="small"
                            />
                        </div>
                    ),
                },
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
