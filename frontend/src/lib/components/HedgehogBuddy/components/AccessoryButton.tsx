import { useActions, useValues } from 'kea'
import { IconLock } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter } from 'lib/utils'

import { hedgehogBuddyLogic } from '../hedgehogBuddyLogic'
import { AccessoryInfo, baseSpriteAccessoriesPath, baseSpritePath } from '../sprites/sprites'

export type HedgehogBuddyAccessoryProps = {
    accessory: AccessoryInfo
    accessoryKey: string
    isDarkModeOn: boolean
}

export function HedgehogBuddyAccessory({
    accessoryKey,
    accessory,
    isDarkModeOn,
}: HedgehogBuddyAccessoryProps): JSX.Element {
    const { accessories, availableAccessories } = useValues(hedgehogBuddyLogic)
    const { addAccessory, removeAccessory } = useActions(hedgehogBuddyLogic)

    const isUnlocked = availableAccessories.includes(accessoryKey)

    const onClick = (): void => {
        if (!accessories.includes(accessory) && isUnlocked) {
            addAccessory(accessory)
        } else {
            removeAccessory(accessory)
        }
    }

    const imgExt = isDarkModeOn ? 'dark.png' : 'png'
    const imgSize = 60
    const hedgehogImgSize = imgSize * 4

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={onClick}
            active={accessories.includes(accessory)}
            noPadding
            tooltip={
                <>
                    {capitalizeFirstLetter(accessoryKey)}
                    {isUnlocked ? '' : ' (not available - can be unlocked by trying different things in PostHog...)'}
                </>
            }
        >
            {!isUnlocked && <IconLock className=" absolute right-0 top-0 rounded" />}
            <div
                className="relative overflow-hidden pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: imgSize,
                    height: imgSize,
                }}
            >
                <img
                    src={`${baseSpritePath()}/wave.${imgExt}`}
                    className="object-cover absolute inset-0 image-pixelated"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: hedgehogImgSize,
                        height: hedgehogImgSize,
                    }}
                />

                <img
                    src={`${baseSpriteAccessoriesPath()}/${accessory.img}.${imgExt}`}
                    className="object-cover absolute inset-0 image-pixelated"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: imgSize,
                        height: imgSize,
                    }}
                />
            </div>
        </LemonButton>
    )
}
