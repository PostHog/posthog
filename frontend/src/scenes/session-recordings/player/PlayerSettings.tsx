import { IconFastForward, IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { playerSettingsLogic } from './playerSettingsLogic'

export const PlayerSettings = (): JSX.Element => {
    const { autoplayDirection, skipInactivitySetting, showMouseTail } = useValues(playerSettingsLogic)
    const { setAutoplayDirection, setSkipInactivitySetting, setShowMouseTail } = useActions(playerSettingsLogic)

    return (
        <LemonMenu
            closeOnClickInside={false}
            items={[
                {
                    custom: true,
                    label: () => (
                        <div className="flex flex-row items-center justify-between space-x-2 p-1 pl-1 min-w-64">
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
                                dropdownPlacement="bottom-end"
                                dropdownMatchSelectWidth={false}
                                options={[
                                    { value: null, label: 'Off' },
                                    { value: 'newer', label: 'Newer recordings' },
                                    { value: 'older', label: 'Older recordings' },
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
            ]}
        >
            <LemonButton size="small" icon={<IconGear />} />
        </LemonMenu>
    )
}
