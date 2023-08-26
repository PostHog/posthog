import { Meta } from '@storybook/react'
import { Popover } from './Popover/Popover'
import { useState } from 'react'

const meta: Meta = {
    title: 'Lemon UI/Colors',
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

const colorGroups = {
    primary: ['primary-highlight', 'primary-light', 'primary', 'primary-dark'],
    danger: ['danger-highlight', 'danger-light', 'danger', 'danger-dark'],
    warning: ['warning-highlight', 'warning-light', 'warning', 'warning-dark'],
    success: ['success-highlight', 'success-light', 'success', 'success-dark'],
    'primary-alt': ['primary-alt-highlight', 'primary-alt', 'primary-alt-dark'],
    'default (primary text)': ['default', 'default-dark'],
    'muted (secondary text)': ['muted', 'muted-dark'],
    'muted-alt ': ['muted-alt', 'muted-alt-dark'],
    border: ['border', 'border-light', 'border-bold', 'border-active'],
    light: ['white', 'light'],
}

const preThousand = [
    'primary-highlight',
    'primary-light',
    'primary',
    'primary-dark',
    'danger-highlight',
    'danger-lighter',
    'danger-light',
    'danger',
    'danger-dark',
    'warning-highlight',
    'warning-light',
    'warning',
    'warning-dark',
    'success-highlight',
    'success-light',
    'success',
    'success-dark',
    'primary-alt-highlight',
    'primary-alt',
    'primary-alt-dark',
    'default',
    'default-dark',
    'muted',
    'muted-dark',
    'muted-alt',
    'muted-alt-dark',
    'mark',
    'white',
    'bg-light',
    'side',
    'mid',
    'border',
    'border-light',
    'border-bold',
    'border-active',
    'transparent',
    'brand-blue',
    'brand-red',
    'brand-yellow',
    'brand-key',
]

const threeThousand = [
    'text-3000-light',
    'muted-3000-light',
    'trace-3000-light',
    'primary-3000-light',
    'primary-3000-hover-light',
    'secondary-3000-light',
    'secondary-3000-hover-light',
    'accent-3000-light',
    'bg-3000-light',
    'border-3000-light',
    'border-bold-3000-light',
    'glass-bg-3000-light',
    'glass-border-3000-light',
    'text-3000-dark',
    'muted-3000-dark',
    'trace-3000-dark',
    'primary-3000-dark',
    'primary-3000-hover-dark',
    'secondary-3000-dark',
    'secondary-3000-hover-dark',
    'accent-3000-dark',
    'bg-3000-dark',
    'border-3000-dark',
    'border-bold-3000-dark',
    'glass-bg-3000-dark',
    'glass-border-3000-dark',
    'text-3000',
    'muted-3000',
    'trace-3000',
    'primary-3000',
    'primary-3000-hover',
    'secondary-3000',
    'secondary-3000-hover',
    'accent-3000',
    'bg-3000',
    'border-3000',
    'border-bold-3000',
    'glass-bg-3000',
    'glass-border-3000',
]

export function ColorPalette(): JSX.Element {
    const [hover, setHover] = useState<string>()
    return (
        <div className="flex gap-4 flex-wrap items-start">
            {Object.keys(colorGroups).map((group) => (
                <div key={group} className="flex flex-col" style={{ width: 150, height: 200 }}>
                    <div className="font-bold text-ellipsis mb-2">{group}</div>
                    <div className="rounded-lg overflow-hidden flex flex-col flex-1">
                        {colorGroups[group].map((color: string) => (
                            <Popover
                                key={color}
                                visible={hover === color}
                                placement="right"
                                overlay={
                                    <>
                                        <h3>{color}</h3>
                                    </>
                                }
                            >
                                <div className={`bg-${color} flex-1`} onMouseEnter={() => setHover(color)} />
                            </Popover>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

function ColorList({ title, colors }: { title: string; colors: string[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-4 rounded-lg border px-4 py-2">
            <h1>{title}</h1>
            <div className={'flex flex-wrap gap-2'}>
                {colors.map((color) => (
                    <div key={color}>
                        <div className={'flex flex-row space-x-2 border rounded-lg items-center pl-2'}>
                            {color}
                            <div className={`bg-${color} flex-1 border rounded ml-2 h-8 w-8`} />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

export function AllPreThousandColorOptions(): JSX.Element {
    return <ColorList title={'Pre-thousand colors'} colors={preThousand} />
}

export function AllThreeThousandColorOptions(): JSX.Element {
    return <ColorList title={'PostHog-3000 colors'} colors={threeThousand} />
}
