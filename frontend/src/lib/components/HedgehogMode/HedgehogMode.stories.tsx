import { Meta, StoryFn } from '@storybook/react'

import { HedgehogModeStatic, HedgehogModeStaticProps } from './HedgehogModeStatic'

const meta: Meta<typeof HedgehogModeStatic> = {
    title: 'HedgehogMode',
    component: HedgehogModeStatic,
    tags: ['autodocs'],
}
export default meta

const EXAMPLES: HedgehogModeStaticProps[] = [
    { accessories: ['beret', 'xmas-scarf', 'glasses'], color: null, skin: 'default' },
    { accessories: ['chef'], color: 'red', skin: 'default' },
    { skin: 'robohog' },
    { skin: 'spiderhog' },
]

export const Customization: StoryFn = () => {
    return (
        <div className="flex flex-wrap gap-2 w-[30rem]">
            {EXAMPLES.map((x, i) => (
                <HedgehogModeStatic key={i} {...x} />
            ))}
        </div>
    )
}
