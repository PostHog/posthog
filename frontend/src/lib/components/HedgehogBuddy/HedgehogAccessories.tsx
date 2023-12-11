import { capitalizeFirstLetter } from 'lib/utils'

import { HedgehogBuddyAccessory } from './components/AccessoryButton'
import { accessoryGroups, standardAccessories } from './sprites/sprites'

export function HedgehogAccessories({ isDarkModeOn }: { isDarkModeOn: boolean }): JSX.Element {
    return (
        <>
            <h3>Hi, I'm Max!</h3>
            <p>
                Don't mind me. I'm just here to keep you company.
                <br />
                You can move me around by clicking and dragging or control me with WASD / arrow keys.
            </p>

            {accessoryGroups.map((group) => (
                <div key={group}>
                    <h4>{capitalizeFirstLetter(group)}</h4>

                    <div className="flex gap-2 pb-2 pt-px overflow-y-auto">
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
