import { IconLock } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter } from 'lib/utils'

import { hedgehogBuddyLogic } from '../hedgehogBuddyLogic'
import { AccessoryInfo, baseSpriteAccessoriesPath, baseSpritePath } from '../sprites/sprites'

export type HedgehogBuddyAccessoryProps = {
    accessory: AccessoryInfo
    accessoryKey: string
}

export function HedgehogBuddyAccessory({ accessoryKey, accessory }: HedgehogBuddyAccessoryProps): JSX.Element {
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

    const imgSize = 60
    const hedgehogImgSize = imgSize * 4

    const enabled = accessories.includes(accessory)

    return (
        <LemonButton
            className={clsx('border border-2', enabled ? 'border-primary' : 'border-transparent')}
            size="small"
            onClick={onClick}
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
                    margin: -2,
                }}
            >
                <img
                    src={`${baseSpritePath()}/wave.png`}
                    className="object-cover absolute inset-0 image-pixelated"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: hedgehogImgSize,
                        height: hedgehogImgSize,
                    }}
                />

                <img
                    src={`${baseSpriteAccessoriesPath()}/${accessory.img}.png`}
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
