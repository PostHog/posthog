import * as icons from '@posthog/icons'
import { Meta } from '@storybook/react'

import { LemonCollapse } from '../LemonCollapse'

const meta: Meta = {
    title: 'PostHog 3000/Icons',
    tags: ['autodocs'],
}
export default meta

const posthogIcons = Object.entries(icons)
    .filter(([key]) => key !== 'IconBase')
    .map(([key, Icon]) => ({ name: key, icon: Icon }))

const CATEGORIES = {
    Arrows: [
        'IconArrowLeft',
        'IconArrowRight',
        'IconArrowCircleLeft',
        'IconArrowCircleRight',
        'IconArrowRightDown',
        'IconArrowUpRight',
    ],
}

const IconTemplate = ({ icons }: { icons: { name: string; icon: any }[] }): JSX.Element => {
    return (
        <div className="grid grid-cols-6 gap-4">
            {icons.map(({ name, icon: Icon }) => {
                return (
                    <div key={name} className="flex flex-col items-center">
                        <Icon className="w-10 h-10" />
                        <span className="text-xs">{name}</span>
                    </div>
                )
            })}
        </div>
    )
}

export function AlphabeticalIcons(): JSX.Element {
    return <IconTemplate icons={posthogIcons} />
}

export function CategoricalIcons(): JSX.Element {
    return (
        <LemonCollapse
            multiple
            panels={[
                ...Object.keys(CATEGORIES).map((key) => {
                    return {
                        key,
                        header: key,
                        content: (
                            <IconTemplate
                                icons={Object.entries(key).map(([_, icon]) => {
                                    return { name: icon.name, icon: icon }
                                })}
                            />
                        ),
                    }
                }),
            ]}
        />
    )
}
