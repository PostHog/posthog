import { Meta } from '@storybook/react'
import { useState } from 'react'

import { LemonTable } from './LemonTable'
import { Popover } from './Popover/Popover'

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

const colorGroups: Record<string, string[]> = {
    primary: ['primary-highlight', 'primary'],
    danger: ['danger-highlight', 'danger-light', 'danger', 'danger-dark'],
    warning: ['warning-highlight', 'warning', 'warning-dark'],
    success: ['success-highlight', 'success-light', 'success', 'success-dark'],
    'primary-alt': ['primary-alt-highlight', 'primary-alt'],
    text: ['muted', 'default'],
    border: ['border', 'border-light', 'border-bold'],
    light: ['white', 'light'],
}

const preThousand = [
    'primary-highlight',
    'primary',
    'danger-highlight',
    'danger-lighter',
    'danger-light',
    'danger',
    'danger-dark',
    'warning-highlight',
    'warning',
    'warning-dark',
    'success-highlight',
    'success-light',
    'success',
    'success-dark',
    'primary-alt-highlight',
    'primary-alt',
    'muted',
    'muted-alt',
    'mark',
    'white',
    'bg-light',
    'side',
    'mid',
    'border',
    'border-light',
    'border-bold',
    'transparent',
    'brand-blue',
    'brand-red',
    'brand-yellow',
    'brand-key',
]

const threeThousand = [
    {
        name: 'danger-highlight',
        value: 'bg-danger-highlight',
        newLight: 'bg-fill-danger-secondary',
        newDark: 'bg-fill-danger-secondary',
    },
    {
        name: 'danger-lighter',
        value: 'bg-danger-lighter',
        newLight: 'bg-primitive-red-200',
        newDark: 'bg-primitive-red-200',
    },
    {
        name: 'danger-light',
        value: 'bg-danger-light',
        newLight: 'bg-primitive-red-500',
        newDark: 'bg-primitive-red-500',
    },
    {
        name: 'danger',
        value: 'bg-danger',
        newLight: 'bg-primitive-red-500',
        newDark: 'bg-primitive-red-500',
    },
    {
        name: 'danger-dark',
        value: 'bg-danger-dark',
        newLight: 'bg-danger-dark-light',
        newDark: 'bg-danger-dark-dark',
    },
    {
        name: 'warning-highlight',
        value: 'bg-warning-highlight',
        newLight: 'bg-warning-highlight-light',
        newDark: 'bg-warning-highlight-dark',
    },
    {
        name: 'warning',
        value: 'bg-warning',
        newLight: 'bg-warning-light',
        newDark: 'bg-warning-dark',
    },
    {
        name: 'warning-dark',
        value: 'bg-warning-dark',
        newLight: 'bg-warning-dark-light',
        newDark: 'bg-warning-dark-dark',
    },
    {
        name: 'success-highlight',
        value: 'bg-success-highlight',
        newLight: 'bg-success-highlight-light',
        newDark: 'bg-success-highlight-dark',
    },
    {
        name: 'success-light',
        value: 'bg-success-light',
        newLight: 'bg-success-light-light',
        newDark: 'bg-success-light-dark',
    },
    {
        name: 'success',
        value: 'bg-success',
        newLight: 'bg-success-light',
        newDark: 'bg-success-dark',
    },
    {
        name: 'success-dark',
        value: 'bg-success-dark',
        newLight: 'bg-success-dark-light',
        newDark: 'bg-success-dark-dark',
    },
    {
        name: 'muted',
        value: 'bg-muted',
        newLight: 'bg-muted-light',
        newDark: 'bg-muted-dark',
    },
    {
        name: 'muted-alt',
        value: 'bg-muted-alt',
        newLight: 'bg-muted-alt-light',
        newDark: 'bg-muted-alt-dark',
    },
    {
        name: 'mark',
        value: 'bg-mark',
        newLight: 'bg-mark-light',
        newDark: 'bg-mark-dark',
    },
    {
        name: 'white',
        value: 'bg-white',
        newLight: 'bg-white-light',
        newDark: 'bg-white-dark',
    },
    {
        name: 'bg-light',
        value: 'bg-light',
        newLight: 'bg-light-light',
        newDark: 'bg-light-dark',
    },
    {
        name: 'side',
        value: 'bg-side',
        newLight: 'bg-side-light',
        newDark: 'bg-side-dark',
    },
    {
        name: 'mid',
        value: 'bg-mid',
        newLight: 'bg-mid-light',
        newDark: 'bg-mid-dark',
    },
    {
        name: 'border',
        value: 'bg-border',
        newLight: 'bg-border-light',
        newDark: 'bg-border-dark',
    },
    {
        name: 'border-light',
        value: 'bg-border-light',
        newLight: 'bg-border-light-light',
        newDark: 'bg-border-light-dark',
    },
    {
        name: 'border-bold',
        value: 'bg-border-bold',
        newLight: 'bg-border-bold-light',
        newDark: 'bg-border-bold-dark',
    },
    {
        name: 'transparent',
        value: 'bg-transparent',
        newLight: 'bg-transparent-light',
        newDark: 'bg-transparent-dark',
    },
    {
        name: 'link',
        value: 'bg-link',
        newLight: 'bg-link-light',
        newDark: 'bg-link-dark',
    },
    // Colors of the PostHog logo
    {
        name: 'brand-blue',
        value: 'bg-brand-blue',
        newLight: 'bg-brand-blue-light',
        newDark: 'bg-brand-blue-dark',
    },
    {
        name: 'brand-red',
        value: 'bg-brand-red',
        newLight: 'bg-brand-red-light',
        newDark: 'bg-brand-red-dark',
    },
    {
        name: 'brand-yellow',
        value: 'bg-brand-yellow',
        newLight: 'bg-brand-yellow-light',
        newDark: 'bg-brand-yellow-dark',
    },
    {
        name: 'brand-key',
        value: 'bg-brand-key',
        newLight: 'bg-brand-key-light',
        newDark: 'bg-brand-key-dark',
    },

    // PostHog 3000
    {
        name: 'text-3000-light',
        value: 'bg-text-3000-light',
        newLight: 'bg-text-3000-light',
        newDark: 'bg-text-3000-dark',
    },
    {
        name: 'text-secondary-3000-light',
        value: 'bg-text-secondary-3000-light',
        newLight: 'bg-text-secondary-3000-light',
        newDark: 'bg-text-secondary-3000-dark',
    },
    {
        name: 'muted-3000-light',
        value: 'bg-muted-3000-light',
        newLight: 'bg-muted-3000-light',
        newDark: 'bg-muted-3000-dark',
    },
    {
        name: 'trace-3000-light',
        value: 'bg-trace-3000-light',
        newLight: 'bg-trace-3000-light',
        newDark: 'bg-trace-3000-dark',
    },
    {
        name: 'primary-3000-light',
        value: 'bg-primary-3000-light',
        newLight: 'bg-primary-3000-light',
        newDark: 'bg-primary-3000-dark',
    },
    {
        name: 'primary-highlight-light',
        value: 'bg-primary-highlight-light',
        newLight: 'bg-primary-highlight-light',
        newDark: 'bg-primary-highlight-dark',
    },
    {
        name: 'primary-3000-hover-light',
        value: 'bg-primary-3000-hover-light',
        newLight: 'bg-primary-3000-hover-light',
        newDark: 'bg-primary-3000-hover-dark',
    },
    {
        name: 'primary-3000-active-light',
        value: 'bg-primary-3000-active-light',
        newLight: 'bg-primary-3000-active-light',
        newDark: 'bg-primary-3000-active-dark',
    },
    {
        name: 'secondary-3000-light',
        value: 'bg-secondary-3000-light',
        newLight: 'bg-secondary-3000-light',
        newDark: 'bg-secondary-3000-dark',
    },
    {
        name: 'secondary-3000-hover-light',
        value: 'bg-secondary-3000-hover-light',
        newLight: 'bg-secondary-3000-hover-light',
        newDark: 'bg-secondary-3000-hover-dark',
    },
    {
        name: 'accent-3000-light',
        value: 'bg-accent-3000-light',
        newLight: 'bg-accent-3000-light',
        newDark: 'bg-accent-3000-dark',
    },
    {
        name: 'bg-3000-light',
        value: 'bg-bg-3000-light',
        newLight: 'bg-bg-3000-light',
        newDark: 'bg-bg-3000-dark',
    },
    {
        name: 'border-3000-light',
        value: 'bg-border-3000-light',
        newLight: 'bg-border-3000-light',
        newDark: 'bg-border-3000-dark',
    },
    {
        name: 'border-bold-3000-light',
        value: 'bg-border-bold-3000-light',
        newLight: 'bg-border-bold-3000-light',
        newDark: 'bg-border-bold-3000-dark',
    },
    {
        name: 'glass-bg-3000-light',
        value: 'bg-glass-bg-3000-light',
        newLight: 'bg-glass-bg-3000-light',
        newDark: 'bg-glass-bg-3000-dark',
    },

    {
        name: 'link-3000-light',
        value: 'bg-link-3000-light',
        newLight: 'bg-link-3000-light',
        newDark: 'bg-link-3000-dark',
    },
    {
        name: 'primary-3000-frame-bg-light',
        value: 'bg-primary-3000-frame-bg-light',
        newLight: 'bg-primary-3000-frame-bg-light',
        newDark: 'bg-primary-3000-frame-bg-dark',
    },
    {
        name: 'primary-3000-button-bg-light',
        value: 'bg-primary-3000-button-bg-light',
        newLight: 'bg-primary-3000-button-bg-light',
        newDark: 'bg-primary-3000-button-bg-dark',
    },
    {
        name: 'primary-3000-button-border-light',
        value: 'bg-primary-3000-button-border-light',
        newLight: 'bg-primary-3000-button-border-light',
        newDark: 'bg-primary-3000-button-border-dark',
    },
    {
        name: 'primary-3000-button-border-hover-light',
        value: 'bg-primary-3000-button-border-hover-light',
        newLight: 'bg-primary-3000-button-border-hover-light',
        newDark: 'bg-primary-3000-button-border-hover-dark',
    },

    {
        name: 'secondary-3000-frame-bg-light',
        value: 'bg-secondary-3000-frame-bg-light',
        newLight: 'bg-secondary-3000-frame-bg-light',
        newDark: 'bg-secondary-3000-frame-bg-dark',
    },
    {
        name: 'secondary-3000-button-bg-light',
        value: 'bg-secondary-3000-button-bg-light',
        newLight: 'bg-secondary-3000-button-bg-light',
        newDark: 'bg-secondary-3000-button-bg-dark',
    },
    {
        name: 'secondary-3000-button-border-light',
        value: 'bg-secondary-3000-button-border-light',
        newLight: 'bg-secondary-3000-button-border-light',
        newDark: 'bg-secondary-3000-button-border-dark',
    },
    {
        name: 'secondary-3000-button-border-hover-light',
        value: 'bg-secondary-3000-button-border-hover-light',
        newLight: 'bg-secondary-3000-button-border-hover-light',
        newDark: 'bg-secondary-3000-button-border-hover-dark',
    },

    {
        name: 'danger-3000-frame-bg-light',
        value: 'bg-danger-3000-frame-bg-light',
        newLight: 'bg-danger-3000-frame-bg-light',
        newDark: 'bg-danger-3000-frame-bg-dark',
    },
    {
        name: 'danger-3000-button-border-light',
        value: 'bg-danger-3000-button-border-light',
        newLight: 'bg-danger-3000-button-border-light',
        newDark: 'bg-danger-3000-button-border-dark',
    },
    {
        name: 'danger-3000-button-border-hover-light',
        value: 'bg-danger-3000-button-border-hover-light',
        newLight: 'bg-danger-3000-button-border-hover-light',
        newDark: 'bg-danger-3000-button-border-hover-dark',
    },

    {
        name: 'shadow-elevation-3000-light',
        value: 'bg-shadow-elevation-3000-light',
        newLight: 'bg-shadow-elevation-3000-light',
        newDark: 'bg-shadow-elevation-3000-dark',
    },
    {
        name: 'shadow-elevation-3000-dark',
        value: 'bg-shadow-elevation-3000-dark',
        newLight: 'bg-shadow-elevation-3000-light',
        newDark: 'bg-shadow-elevation-3000-dark',
    },
    {
        name: 'text-3000-dark',
        value: 'bg-text-3000-dark',
        newLight: 'bg-text-3000-light',
        newDark: 'bg-text-3000-dark',
    },
    {
        name: 'text-secondary-3000-dark',
        value: 'bg-text-secondary-3000-dark',
        newLight: 'bg-text-secondary-3000-light',
        newDark: 'bg-text-secondary-3000-dark',
    },
    {
        name: 'muted-3000-dark',
        value: 'bg-muted-3000-dark',
        newLight: 'bg-muted-3000-light',
        newDark: 'bg-muted-3000-dark',
    },
    {
        name: 'trace-3000-dark',
        value: 'bg-trace-3000-dark',
        newLight: 'bg-trace-3000-light',
        newDark: 'bg-trace-3000-dark',
    },
    {
        name: 'primary-3000-dark',
        value: 'bg-primary-3000-dark',
        newLight: 'bg-primary-3000-light',
        newDark: 'bg-primary-3000-dark',
    },
    {
        name: 'primary-highlight-dark',
        value: 'bg-primary-highlight-dark',
        newLight: 'bg-primary-highlight-light',
        newDark: 'bg-primary-highlight-dark',
    },
    {
        name: 'primary-3000-hover-dark',
        value: 'bg-primary-3000-hover-dark',
        newLight: 'bg-primary-3000-hover-light',
        newDark: 'bg-primary-3000-hover-dark',
    },
    {
        name: 'primary-3000-active-dark',
        value: 'bg-primary-3000-active-dark',
        newLight: 'bg-primary-3000-active-light',
        newDark: 'bg-primary-3000-active-dark',
    },
    {
        name: 'primary-alt-highlight-dark',
        value: 'bg-primary-alt-highlight-dark',
        newLight: 'bg-primary-alt-highlight-light',
        newDark: 'bg-primary-alt-highlight-dark',
    },

    {
        name: 'secondary-3000-dark',
        value: 'bg-secondary-3000-dark',
        newLight: 'bg-secondary-3000-light',
        newDark: 'bg-secondary-3000-dark',
    },
    {
        name: 'secondary-3000-hover-dark',
        value: 'bg-secondary-3000-hover-dark',
        newLight: 'bg-secondary-3000-hover-light',
        newDark: 'bg-secondary-3000-hover-dark',
    },
    {
        name: 'accent-3000-dark',
        value: 'bg-accent-3000-dark',
        newLight: 'bg-accent-3000-light',
        newDark: 'bg-accent-3000-dark',
    },
    {
        name: 'bg-3000-dark',
        value: 'bg-bg-3000-dark',
        newLight: 'bg-bg-3000-light',
        newDark: 'bg-bg-3000-dark',
    },
    {
        name: 'glass-border-3000-dark',
        value: 'bg-glass-border-3000-dark',
        newLight: 'bg-glass-border-3000-light',
        newDark: 'bg-glass-border-3000-dark',
    },
    {
        name: 'link-3000-dark',
        value: 'bg-link-3000-dark',
        newLight: 'bg-link-3000-light',
        newDark: 'bg-link-3000-dark',
    },

    {
        name: 'primary-3000-frame-bg-dark',
        value: 'bg-primary-3000-frame-bg-dark',
        newLight: 'bg-primary-3000-frame-bg-light',
        newDark: 'bg-primary-3000-frame-bg-dark',
    },
    {
        name: 'primary-3000-button-bg-dark',
        value: 'bg-primary-3000-button-bg-dark',
        newLight: 'bg-primary-3000-button-bg-light',
        newDark: 'bg-primary-3000-button-bg-dark',
    },
    {
        name: 'primary-3000-button-border-dark',
        value: 'bg-primary-3000-button-border-dark',
        newLight: 'bg-primary-3000-button-border-light',
        newDark: 'bg-primary-3000-button-border-dark',
    },
    {
        name: 'primary-3000-button-border-hover-dark',
        value: 'bg-primary-3000-button-border-hover-dark',
        newLight: 'bg-primary-3000-button-border-hover-light',
        newDark: 'bg-primary-3000-button-border-hover-dark',
    },
    {
        name: 'primary-alt-highlight-dark',
        value: 'bg-primary-alt-highlight-dark',
        newLight: 'bg-primary-alt-highlight-light',
        newDark: 'bg-primary-alt-highlight-dark',
    },

    {
        name: 'secondary-3000-frame-bg-dark',
        value: 'bg-secondary-3000-frame-bg-dark',
        newLight: 'bg-secondary-3000-frame-bg-light',
        newDark: 'bg-secondary-3000-frame-bg-dark',
    },
    {
        name: 'secondary-3000-button-bg-dark',
        value: 'bg-secondary-3000-button-bg-dark',
        newLight: 'bg-secondary-3000-button-bg-light',
        newDark: 'bg-secondary-3000-button-bg-dark',
    },
    {
        name: 'secondary-3000-button-border-dark',
        value: 'bg-secondary-3000-button-border-dark',
        newLight: 'bg-secondary-3000-button-border-light',
        newDark: 'bg-secondary-3000-button-border-dark',
    },
    {
        name: 'secondary-3000-button-border-hover-dark',
        value: 'bg-secondary-3000-button-border-hover-dark',
        newLight: 'bg-secondary-3000-button-border-hover-light',
        newDark: 'bg-secondary-3000-button-border-hover-dark',
    },
    {
        name: 'danger-3000-frame-bg-dark',
        value: 'bg-danger-3000-frame-bg-dark',
        newLight: 'bg-danger-3000-frame-bg-light',
        newDark: 'bg-danger-3000-frame-bg-dark',
    },
    {
        name: 'danger-3000-button-border-dark',
        value: 'bg-danger-3000-button-border-dark',
        newLight: 'bg-danger-3000-button-border-light',
        newDark: 'bg-danger-3000-button-border-dark',
    },
    {
        name: 'danger-3000-button-border-hover-dark',
        value: 'bg-danger-3000-button-border-hover-dark',
        newLight: 'bg-danger-3000-button-border-hover-light',
        newDark: 'bg-danger-3000-button-border-hover-dark',
    },

    // The derived colors
    // `--default` is a pre-3000 alias for "default text color" (`--text-3000` now)
    {
        name: 'default',
        value: 'bg-default',
        newLight: 'bg-text-3000-light',
        newDark: 'bg-text-3000-dark',
    },
    {
        name: 'text-3000',
        value: 'bg-text-3000',
        newLight: 'bg-text-3000-light',
        newDark: 'bg-text-3000-dark',
    },
    {
        name: 'text-secondary-3000',
        value: 'bg-text-secondary-3000',
        newLight: 'bg-text-secondary-3000-light',
        newDark: 'bg-text-secondary-3000-dark',
    },
    {
        name: 'muted-3000',
        value: 'bg-muted-3000',
        newLight: 'bg-muted-3000-light',
        newDark: 'bg-muted-3000-dark',
    },
    {
        name: 'primary-3000',
        value: 'bg-primary-3000',
        newLight: 'bg-primary-3000-light',
        newDark: 'bg-primary-3000-dark',
    },
    {
        name: 'secondary-3000',
        value: 'bg-secondary-3000',
        newLight: 'bg-secondary-3000-light',
        newDark: 'bg-secondary-3000-dark',
    },
    {
        name: 'secondary-3000-hover',
        value: 'bg-secondary-3000-hover',
        newLight: 'bg-secondary-3000-hover-light',
        newDark: 'bg-secondary-3000-hover-dark',
    },
    {
        name: 'accent-3000',
        value: 'bg-accent-3000',
        newLight: 'bg-accent-3000-light',
        newDark: 'bg-accent-3000-dark',
    },
    {
        name: 'bg-3000',
        value: 'bg-bg-3000',
        newLight: 'bg-bg-3000-light',
        newDark: 'bg-bg-3000-dark',
    },
    {
        name: 'primary-highlight',
        value: 'bg-primary-highlight',
        newLight: 'bg-primary-highlight-light',
        newDark: 'bg-primary-highlight-dark',
    },
    {
        name: 'primary-alt-highlight',
        value: 'bg-primary-alt-highlight',
        newLight: 'bg-primary-alt-highlight-light',
        newDark: 'bg-primary-alt-highlight-dark',
    },
    {
        name: 'primary-alt',
        value: 'bg-primary-alt',
        newLight: 'bg-primary-alt-light',
        newDark: 'bg-primary-alt-dark',
    },
]

export function ColorPalette(): JSX.Element {
    const [hover, setHover] = useState<string>()
    return (
        <div className="flex gap-4 flex-wrap items-start">
            {Object.keys(colorGroups).map((group) => (
                <div key={group} className="flex flex-col w-40 h-50">
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

export function AllPreThousandColorOptions(): JSX.Element {
    return (
        <LemonTable
            dataSource={preThousand.map((color) => ({ name: color, color }))}
            columns={[
                {
                    title: 'Class name',
                    key: 'name',
                    dataIndex: 'name',
                    render: function RenderName(name) {
                        return name
                    },
                },
                {
                    title: 'Color',
                    key: 'color',
                    dataIndex: 'color',
                    render: function RenderColor(color) {
                        return <div className={`bg-${color as string} flex-1 border rounded h-8 w-8`} />
                    },
                },
            ]}
        />
    )
}

export function AllThreeThousandColorOptions(): JSX.Element {
    // const [hover, setHover] = useState<string>()

    return (
        <>
            <div className="flex flex-col max-w-[500px]">
                <div className="grid grid-cols-[auto_64px_64px_64px_64px]">
                    <div className="text-xs">Name</div>
                    <div className="text-xs">Old</div>
                    <div className="text-xs">New Light</div>
                    <div className="text-xs">Old Dark</div>
                    <div className="text-xs">New Dark</div>
                </div>
                {threeThousand.map((color) => (
                    <div className="grid grid-cols-[auto_64px_64px_64px_64px]" key={color.name}>
                        <div className="text-xs">{color.name}</div>

                        <div key={color.name} className="flex flex-col" title="Old">
                            <div className="flex gap-2 p-4 theme-light bg-primitive-white">
                                <div className={`${color.value} border rounded h-8 w-8`} />
                            </div>
                        </div>
                        <div key={color.name} className="flex flex-col" title="New Light">
                            <div className="flex gap-2 p-4 theme-light bg-primitive-white">
                                <div className={`${color.newLight} border rounded h-8 w-8`} />
                            </div>
                        </div>

                        <div key={color.name} className="flex flex-col" title="Old Dark">
                            <div className="flex gap-2 p-4 theme-dark bg-primitive-black">
                                <div className={`${color.value} border rounded h-8 w-8`} />
                            </div>
                        </div>
                        <div key={color.name} className="flex flex-col" title="New Dark">
                            <div className="flex gap-2 p-4 theme-dark bg-primitive-black">
                                <div className={`${color.newDark} border rounded h-8 w-8`} />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
            <LemonTable
                dataSource={threeThousand.map((color) => ({ name: color.name, color: color.value }))}
                columns={[
                    {
                        title: 'Class name',
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderName(name) {
                            return name
                        },
                    },
                    {
                        title: 'Light mode',
                        key: 'light',
                        dataIndex: 'color',
                        render: function RenderColor(color) {
                            return (
                                <div className="bg-bg-3000-light flex items-center justify-center border rounded h-16 w-16">
                                    <div className={`${color as string} border rounded h-8 w-8`} />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Light mode (New)',
                        key: 'light-new',
                        dataIndex: 'color',
                        render: function RenderColor(color) {
                            return (
                                <div className="bg-bg-3000-light flex items-center justify-center border rounded h-16 w-16">
                                    <div className={`${color as string} border rounded h-8 w-8`} />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Dark mode',
                        key: 'dark',
                        dataIndex: 'color',
                        render: function RenderColor(color) {
                            return (
                                <div className="bg-bg-3000-dark flex items-center justify-center border rounded h-16 w-16">
                                    <div className={`${color as string} border rounded h-8 w-8`} />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Dark mode (New)',
                        key: 'dark-new',
                        dataIndex: 'color',
                        render: function RenderColor(color) {
                            return <div className={`${color as string} border rounded h-8 w-8`} />
                        },
                    },
                ]}
            />
        </>
    )
}
