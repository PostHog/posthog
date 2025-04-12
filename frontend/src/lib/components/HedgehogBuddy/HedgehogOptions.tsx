import {
    HedgehogActorAccessories,
    HedgehogActorAccessoryOption,
    HedgehogActorAccessoryOptions,
    HedgehogActorColorOptions,
    HedgehogActorSkinOption,
} from '@posthog/hedgehog-mode'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'

import { HedgehogBuddyProfile, HedgehogBuddyStatic } from './HedgehogBuddyRender'
import { hedgehogModeLogic } from './hedgehogModeLogic'

const ACCESSORY_GROUPS = ['headwear', 'eyewear', 'other'] as const

export function HedgehogOptions(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { patchHedgehogConfig } = useActions(hedgehogModeLogic)

    return (
        <div>
            <div className="flex items-start gap-2">
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
                <div className="flex flex-wrap items-center gap-2">
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
                <HedgehogSkins />
                <HedgehogColor />
                <HedgehogAccessories />
            </div>
        </div>
    )
}

function HedgehogAccessories(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { patchHedgehogConfig } = useActions(hedgehogModeLogic)

    const accessories = hedgehogConfig.accessories.filter((acc) => !!HedgehogActorAccessories[acc])

    const onClick = (accessory: HedgehogActorAccessoryOption): void => {
        // If it is in the list - remove it
        // If it isn't in the list, remove all accessories of the same group and add the new one

        if (accessories.includes(accessory)) {
            patchHedgehogConfig({
                accessories: accessories.filter((acc) => acc !== accessory),
            })
        } else {
            patchHedgehogConfig({
                accessories: accessories
                    .filter((acc) => HedgehogActorAccessories[acc].group !== HedgehogActorAccessories[accessory].group)
                    .concat(accessory),
            })
        }
    }

    return (
        <>
            {ACCESSORY_GROUPS.map((group) => (
                <React.Fragment key={group}>
                    <h4>{capitalizeFirstLetter(group)}</h4>

                    <div className="flex flex-wrap gap-2 pt-px pb-2 overflow-y-auto">
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

function HedgehogSkins(): JSX.Element | null {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { patchHedgehogConfig } = useActions(hedgehogModeLogic)
    const skinSpiderHogEnabled = !!useFeatureFlag('HEDGEHOG_SKIN_SPIDERHOG') || hedgehogConfig.skin === 'spiderhog'

    const skins: HedgehogActorSkinOption[] = skinSpiderHogEnabled ? ['default', 'spiderhog'] : ['default']

    if (skins.length === 1) {
        return null
    }

    return (
        <>
            <h4>Skins</h4>

            <div className="flex flex-wrap items-center gap-2">
                {skins.map((option) => (
                    <LemonButton
                        key={option}
                        className={clsx(
                            'border-2',
<<<<<<< HEAD
                            hedgehogConfig.skin === option ? 'border-accent-primary' : 'border-transparent'
=======
                            !hedgehogConfig.color && hedgehogConfig.skin === option
                                ? 'border-accent'
                                : 'border-transparent'
>>>>>>> master
                        )}
                        size="small"
                        onClick={() => patchHedgehogConfig({ skin: option as any })}
                        noPadding
                        tooltip={<>{capitalizeFirstLetter(option ?? 'default')}</>}
                    >
                        <HedgehogBuddyStatic skin={option} />
                    </LemonButton>
                ))}
            </div>
        </>
    )
}

function HedgehogColor(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { patchHedgehogConfig } = useActions(hedgehogModeLogic)

    return (
        <>
            <h4>Colors</h4>

            <div className="flex flex-wrap items-center gap-2">
                {['none', ...HedgehogActorColorOptions].map((option) => (
                    <LemonButton
                        key={option}
                        className={clsx(
                            'border-2',
                            hedgehogConfig.color === option ? 'border-accent' : 'border-transparent'
                        )}
                        size="small"
                        onClick={() => patchHedgehogConfig({ color: option === 'none' ? null : (option as any) })}
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
