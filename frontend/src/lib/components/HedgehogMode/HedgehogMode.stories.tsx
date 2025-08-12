import {
    HedgehogActorAccessoryOptions,
    HedgehogActorColorOptions,
    HedgehogActorSkinOptions,
} from '@posthog/hedgehog-mode'
import { Meta, StoryFn } from '@storybook/react'

import { HedgehogModeStatic } from './HedgehogModeStatic'
import { MinimalHedgehogConfig } from '~/types'

const meta: Meta<typeof HedgehogModeStatic> = {
    title: 'Components/HedgehogMode',
    component: HedgehogModeStatic,
    tags: ['autodocs'],
}
export default meta

// Generate all combinations of accessories, colors, and skins
const allCombinations = Object.values(HedgehogActorAccessoryOptions).flatMap((accessory) =>
    Object.values(HedgehogActorColorOptions).flatMap((color) =>
        Object.values(HedgehogActorSkinOptions).map(
            (skin): MinimalHedgehogConfig => ({
                accessories: [accessory],
                color,
                skin,
                use_as_profile: false,
            })
        )
    )
)

export const Customization: StoryFn = () => {
    return (
        <div className="flex flex-wrap gap-2 w-[100rem]">
            {allCombinations.map((x, i) => (
                <HedgehogModeStatic key={i} config={x} />
            ))}
        </div>
    )
}
