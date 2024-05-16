import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'

import { HedgehogBuddyAccessory } from './components/AccessoryButton'
import { COLOR_TO_FILTER_MAP, hedgehogBuddyLogic } from './hedgehogBuddyLogic'
import { HedgehogBuddyStatic } from './HedgehogBuddyStatic'
import { accessoryGroups, standardAccessories } from './sprites/sprites'

export function HedgehogOptions(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)

    return (
        <div>
            <h3>Hi, I'm Max!</h3>
            <p>
                Don't mind me. I'm just here to keep you company.
                <br />
                You can move me around by clicking and dragging or control me with WASD / arrow keys.
            </p>
            <div className="space-y-2">
                <h4>Options</h4>
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSwitch
                        bordered
                        label="Walk around freely"
                        checked={hedgehogConfig.walking_enabled}
                        onChange={(val) =>
                            patchHedgehogConfig({
                                walking_enabled: val,
                            })
                        }
                        tooltip="If enabled the Hedgehog will walk around the screen, otherwise they will stay in one place. You can still move them around by dragging them."
                    />
                    <LemonSwitch
                        bordered
                        label="Interact with elements"
                        checked={hedgehogConfig.interactions_enabled}
                        onChange={(val) =>
                            patchHedgehogConfig({
                                interactions_enabled: val,
                            })
                        }
                        tooltip="If enabled the Hedgehog might land on elements of the application, otherwise they will always land on the ground"
                    />
                    <LemonSwitch
                        bordered
                        label="Keyboard controls (WASD / arrow keys)"
                        checked={hedgehogConfig.controls_enabled}
                        onChange={(val) =>
                            patchHedgehogConfig({
                                controls_enabled: val,
                            })
                        }
                        tooltip="If enabled you can use the WASD or arrow key + space to move around and jump."
                    />
                </div>
                <HedgehogColor />
                <HedgehogAccessories />
            </div>
        </div>
    )
}

function HedgehogAccessories(): JSX.Element {
    return (
        <>
            {accessoryGroups.map((group) => (
                <React.Fragment key={group}>
                    <h4>{capitalizeFirstLetter(group)}</h4>

                    <div className="flex gap-2 pb-2 pt-px overflow-y-auto flex-wrap">
                        {Object.keys(standardAccessories)
                            .filter((acc) => standardAccessories[acc].group === group)
                            .map((acc) => (
                                <HedgehogBuddyAccessory
                                    key={acc}
                                    accessoryKey={acc}
                                    accessory={standardAccessories[acc]}
                                />
                            ))}
                    </div>
                </React.Fragment>
            ))}
        </>
    )
}

function HedgehogColor(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)

    return (
        <>
            <h4>Colors</h4>

            <div className="flex items-center gap-2 flex-wrap">
                {[null, ...Object.keys(COLOR_TO_FILTER_MAP)].map((option) => (
                    <LemonButton
                        key={option}
                        className={clsx(
                            'border-2',
                            hedgehogConfig.color === option ? 'border-primary' : 'border-transparent'
                        )}
                        size="small"
                        onClick={() => patchHedgehogConfig({ color: option as any })}
                        noPadding
                        tooltip={<>{capitalizeFirstLetter(option ?? 'default')}</>}
                    >
                        <HedgehogBuddyStatic color={option as any} />
                    </LemonButton>
                ))}
            </div>
        </>
    )
}
