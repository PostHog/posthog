import { IconLock } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter } from 'lib/utils'

import { hedgehogBuddyLogic } from '../hedgehogBuddyLogic'
import { HedgehogBuddyStatic } from '../HedgehogBuddyStatic'
import { AccessoryInfo } from '../sprites/sprites'

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

            <HedgehogBuddyStatic accessories={[accessoryKey]} />
        </LemonButton>
    )
}
