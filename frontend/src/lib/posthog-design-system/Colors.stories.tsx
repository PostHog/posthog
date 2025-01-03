import { Meta } from '@storybook/react'
import { useState } from 'react'

import { Popover } from '../lemon-ui/Popover/Popover'

const meta: Meta = {
    title: 'PostHog Design System/Colors',
    parameters: {
        docs: {
            description: {
                component: 'Colors can be used in a variety of ways',
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

const colorGroups: Record<string, { value: string; name: string; description: string }[]> = {
    surface: [
        {
            value: 'bg-surface-secondary',
            name: 'Surface Secondary',
            description: 'The secondary surface color',
        },
        {
            value: 'bg-surface-secondary-hover',
            name: 'Surface Secondary Hover',
            description: 'The secondary surface color when hovered',
        },
    ],
}

export function ColorPalette(): JSX.Element {
    const [hover, setHover] = useState<string>()
    return (
        <div className="flex gap-4 flex-wrap items-start">
            {Object.keys(colorGroups).map((group) => (
                <div key={group} className="flex flex-col w-40 h-50">
                    <div className="font-bold text-ellipsis mb-2">{group}</div>
                    <div className="rounded-lg overflow-hidden flex flex-col flex-1 border border-border-primary">
                        {colorGroups[group].map((color) => (
                            <Popover
                                key={color.value}
                                visible={hover === color.value}
                                placement="right"
                                overlay={
                                    <>
                                        <h3>{color.name}</h3>
                                        <p>{color.description}</p>
                                    </>
                                }
                            >
                                <div className={`${color.value} flex-1`} onMouseEnter={() => setHover(color.value)} />
                            </Popover>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}
