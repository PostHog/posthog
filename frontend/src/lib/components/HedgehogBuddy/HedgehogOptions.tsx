import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'

import { COLOR_TO_FILTER_MAP, hedgehogBuddyLogic } from './hedgehogBuddyLogic'
import { HedgehogBuddyProfile, HedgehogBuddyStatic } from './HedgehogBuddyRender'
import { accessoryGroups, standardAccessories } from './sprites/sprites'

export function HedgehogOptions(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)

    return (
        <div>
            <div className="flex items-start gap-2">
                <HedgehogBuddyProfile {...hedgehogConfig} size={100} />
                <div className="flex-1">
                    <h3>Hi, I'm Max!</h3>
                    <p>
                        Don't mind me. I'm just here to keep you company.
                        <br />
                        You can move me around by clicking and dragging or control me with WASD / arrow keys.
                    </p>
                </div>
            </div>

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
                    <LemonSwitch
                        bordered
                        label="Party mode"
                        checked={hedgehogConfig.party_mode_enabled}
                        onChange={(val) =>
                            patchHedgehogConfig({
                                party_mode_enabled: val,
                            })
                        }
                        tooltip="If enabled then all of your organization members will appear as hedgehogs as well!"
                    />
                </div>
                <HedgehogColor />
                <HedgehogAccessories />
            </div>
        </div>
    )
}

function HedgehogAccessories(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)

    const accessories = hedgehogConfig.accessories

    const onClick = (accessory: string): void => {
        // If it is in the list - remove it
        // If it isn't in the list, remove al accessories of the same group and add the new one

        if (accessories.includes(accessory)) {
            patchHedgehogConfig({
                accessories: accessories.filter((acc) => acc !== accessory),
            })
        } else {
            patchHedgehogConfig({
                accessories: accessories
                    .filter((acc) => standardAccessories[acc].group !== standardAccessories[accessory].group)
                    .concat(accessory),
            })
        }
    }

    return (
        <>
            {accessoryGroups.map((group) => (
                <React.Fragment key={group}>
                    <h4>{capitalizeFirstLetter(group)}</h4>

                    <div className="flex gap-2 pb-2 pt-px overflow-y-auto flex-wrap">
                        {Object.keys(standardAccessories)
                            .filter((acc) => standardAccessories[acc].group === group)
                            .map((acc) => (
                                <LemonButton
                                    key={acc}
                                    className={clsx(
                                        'border-2',
                                        accessories.includes(acc) ? 'border-primary' : 'border-transparent'
                                    )}
                                    size="small"
                                    onClick={() => onClick(acc)}
                                    noPadding
                                    tooltip={<>{capitalizeFirstLetter(acc)}</>}
                                >
                                    <HedgehogBuddyStatic accessories={[acc]} />
                                </LemonButton>
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
