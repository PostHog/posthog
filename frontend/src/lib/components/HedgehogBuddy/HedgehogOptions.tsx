import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { capitalizeFirstLetter } from 'lib/utils'

import { HedgehogSkin } from '~/types'

import { HedgehogBuddyProfile, HedgehogBuddyStatic } from './HedgehogBuddyRender'
import { COLOR_TO_FILTER_MAP, hedgehogBuddyLogic } from './hedgehogBuddyLogic'
import { accessoryGroups, standardAccessories } from './sprites/sprites'

export function HedgehogOptions(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)

    return (
        <div>
            <div className="flex gap-2 items-start">
                <HedgehogBuddyProfile {...hedgehogConfig} size={100} />
                <div className="flex-1">
                    <h3>Hi, I'm Max!</h3>
                    <p>
                        {hedgehogConfig.skin === 'spiderhog' ? (
                            <>
                                Well, it’s not every day you meet a hedgehog with spider powers. Yep, that's me -
                                SpiderHog. I wasn’t always this way. Just your average, speedy little guy until a
                                radioactive spider bit me. With great power comes great responsibility, so buckle up,
                                because this hedgehog’s got a whole data warehouse to protect...
                                <br />
                                You can move me around by clicking and dragging or control me with WASD / arrow keys and
                                I'll use your mouse as a web slinging target.
                            </>
                        ) : (
                            <>
                                Don't mind me. I'm just here to keep you company.
                                <br />
                                You can move me around by clicking and dragging or control me with WASD / arrow keys.
                            </>
                        )}
                    </p>
                </div>
            </div>

            <div className="deprecated-space-y-2">
                <h4>Options</h4>
                <div className="flex flex-wrap gap-2 items-center">
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
                        tooltip="If enabled then all of your organization members will appear in your browser as hedgehogs as well!"
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
        // If it isn't in the list, remove all accessories of the same group and add the new one

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

                    <div className="flex overflow-y-auto flex-wrap gap-2 pt-px pb-2">
                        {Object.keys(standardAccessories)
                            .filter((acc) => standardAccessories[acc].group === group)
                            .map((acc) => (
                                <LemonButton
                                    key={acc}
                                    className={clsx(
                                        'border-2',
                                        accessories.includes(acc) ? 'border-accent' : 'border-transparent'
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
    const skinSpiderHogEnabled = !!useFeatureFlag('HEDGEHOG_SKIN_SPIDERHOG')

    const skins: HedgehogSkin[] = ['default', 'robohog']
    if (skinSpiderHogEnabled) {
        skins.push('spiderhog')
    }

    return (
        <>
            <h4>Skins and colors</h4>

            <div className="flex flex-wrap gap-2 items-center">
                {skins.map((option) => (
                    <LemonButton
                        key={option}
                        className={clsx(
                            'border-2',
                            !hedgehogConfig.color && hedgehogConfig.skin === option
                                ? 'border-accent'
                                : 'border-transparent'
                        )}
                        size="small"
                        onClick={() => patchHedgehogConfig({ skin: option as any, color: null })}
                        noPadding
                        tooltip={<>{capitalizeFirstLetter(option ?? 'default').replace('hog', 'Hog')}</>}
                    >
                        <HedgehogBuddyStatic skin={option} />
                    </LemonButton>
                ))}
                {Object.keys(COLOR_TO_FILTER_MAP).map((option) => (
                    <LemonButton
                        key={option}
                        className={clsx(
                            'border-2',
                            hedgehogConfig.color === option ? 'border-accent' : 'border-transparent'
                        )}
                        size="small"
                        onClick={() => patchHedgehogConfig({ color: option as any, skin: 'default' })}
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
