import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'

import { HedgehogBuddyAccessory } from './components/AccessoryButton'
import { hedgehogBuddyLogic } from './hedgehogBuddyLogic'
import { accessoryGroups, standardAccessories } from './sprites/sprites'

export function HedgehogIntro(): JSX.Element {
    return (
        <>
            <h3>Hi, I'm Max!</h3>
            <p>
                Don't mind me. I'm just here to keep you company.
                <br />
                You can move me around by clicking and dragging or control me with WASD / arrow keys.
            </p>
        </>
    )
}

export function HedgehogOptions(): JSX.Element {
    const { freeMovement, interactWithElements, keyboardControlsEnabled } = useValues(hedgehogBuddyLogic)
    const { setFreeMovement, setInteractWithElements, setKeyboardControlsEnabled } = useActions(hedgehogBuddyLogic)
    return (
        <div className="mb-2">
            <h4>Options</h4>

            <div className="flex items-center gap-2 flex-wrap">
                <LemonSwitch
                    bordered
                    label="Walk around freely"
                    checked={freeMovement}
                    onChange={setFreeMovement}
                    tooltip="If enabled the Hedgehog will walk around the screen, otherwise they will stay in one place. You can still move them around by dragging them."
                />
                <LemonSwitch
                    bordered
                    label="Interact with elements"
                    checked={interactWithElements}
                    onChange={setInteractWithElements}
                    tooltip="If enabled the Hedgehog might land on elements of the application, otherwise they will always land on the ground"
                />
                <LemonSwitch
                    bordered
                    label="Keyboard controls (WASD / arrow keys)"
                    checked={keyboardControlsEnabled}
                    onChange={setKeyboardControlsEnabled}
                    tooltip="If enabled you can use the WASD or arrow key + space to move around and jump."
                />
            </div>
        </div>
    )
}

export function HedgehogAccessories({ isDarkModeOn }: { isDarkModeOn: boolean }): JSX.Element {
    return (
        <>
            {accessoryGroups.map((group) => (
                <div key={group}>
                    <h4>{capitalizeFirstLetter(group)}</h4>

                    <div className="flex gap-2 pb-2 pt-px overflow-y-auto flex-wrap">
                        {Object.keys(standardAccessories)
                            .filter((acc) => standardAccessories[acc].group === group)
                            .map((acc) => (
                                <HedgehogBuddyAccessory
                                    key={acc}
                                    accessoryKey={acc}
                                    accessory={standardAccessories[acc]}
                                    isDarkModeOn={isDarkModeOn}
                                />
                            ))}
                    </div>
                </div>
            ))}
        </>
    )
}
