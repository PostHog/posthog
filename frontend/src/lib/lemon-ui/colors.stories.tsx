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

const colorGroups = {
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
    'bg-primary',
    'bg-danger-highlight',
    'bg-danger-lighter',
    'bg-danger-light',
    'bg-danger',
    'bg-danger-dark',
    'bg-warning-highlight',
    'bg-warning',
    'bg-warning-dark',
    'bg-success-highlight',
    'bg-success-light',
    'bg-success',
    'bg-success-dark',
    'bg-primary-alt-highlight',
    'bg-primary-alt',
    'bg-muted',
    'bg-muted-alt',
    'bg-mark',
    'bg-white',
    'bg-surface-primary',
    'bg-side',
    'bg-mid',
    'bg-border',
    'bg-border-light',
    'bg-border-bold',
    'bg-transparent',
    'bg-brand-blue',
    'bg-brand-red',
    'bg-brand-yellow',
    'bg-brand-key',
]

const threeThousand = [
    ['bg-danger-highlight', 'bg-red-500'],
    ['bg-danger-lighter', 'bg-red-500'],
    ['bg-danger-light', 'bg-red-500'],
    ['bg-danger', 'bg-red-500'],
    ['bg-danger-dark', 'bg-red-500'],
    ['bg-warning-highlight', 'bg-red-500'],
    ['bg-warning', 'bg-red-500'],
    ['bg-warning-dark', 'bg-red-500'],
    ['bg-highlight', 'bg-red-500'],
    ['bg-success-highlight', 'bg-red-500'],
    ['bg-success-light', 'bg-red-500'],
    ['bg-success', 'bg-red-500'],
    ['bg-success-dark', 'bg-red-500'],
    ['bg-muted', 'bg-red-500'],
    ['bg-muted-alt', 'bg-red-500'],
    ['bg-mark', 'bg-red-500'],
    ['bg-white', 'bg-red-500'],
    ['bg-side', 'bg-red-500'],
    ['bg-mid', 'bg-red-500'],
    ['bg-border', 'bg-red-500'],
    ['bg-border-light', 'bg-red-500'],
    ['bg-border-bold', 'bg-red-500'],
    ['bg-transparent', 'bg-red-500'],
    ['bg-link', 'bg-red-500'],
    // Colors of the PostHog logo
    ['bg-brand-blue', 'bg-red-500'],
    ['bg-brand-red', 'bg-red-500'],
    ['bg-brand-yellow', 'bg-red-500'],
    ['bg-brand-key', 'bg-red-500'],

    // PostHog 3000
    ['bg-text-3000-light', 'bg-red-500'],
    ['bg-text-secondary-3000-light', 'bg-red-500'],
    ['bg-muted-3000-light', 'bg-red-500'],
    ['bg-trace-3000-light', 'bg-red-500'],
    ['bg-primary-3000-light', 'bg-red-500'],
    ['bg-primary-highlight-light', 'bg-red-500'],
    ['bg-primary-3000-hover-light', 'bg-red-500'],
    ['bg-primary-3000-active-light', 'bg-red-500'],

    ['bg-secondary-3000-light', 'bg-red-500'],
    ['bg-secondary-3000-hover-light', 'bg-red-500'],
    ['bg-primary-light', 'bg-red-500'],
    ['bg-border-3000-light', 'bg-red-500'],
    ['bg-border-bold-3000-light', 'bg-red-500'],
    ['bg-glass-bg-3000-light', 'bg-red-500'],
    ['bg-glass-border-3000-light', 'bg-red-500'],

    ['bg-link-3000-light', 'bg-red-500'],
    ['bg-primary-3000-frame-bg-light', 'bg-red-500'],
    ['bg-primary-3000-button-bg-light', 'bg-red-500'],
    ['bg-primary-3000-button-border-light', 'bg-red-500'],
    ['bg-primary-3000-button-border-hover-light', 'bg-red-500'],

    ['bg-secondary-3000-frame-bg-light', 'bg-red-500'],
    ['bg-secondary-3000-button-bg-light', 'bg-red-500'],
    ['bg-secondary-3000-button-border-light', 'bg-red-500'],
    ['bg-secondary-3000-button-border-hover-light', 'bg-red-500'],

    ['bg-danger-3000-frame-bg-light', 'bg-red-500'],
    ['bg-danger-3000-button-border-light', 'bg-red-500'],
    ['bg-danger-3000-button-border-hover-light', 'bg-red-500'],

    ['bg-text-3000-dark', 'bg-red-500'],
    ['bg-text-secondary-3000-dark', 'bg-red-500'],
    ['bg-muted-3000-dark', 'bg-red-500'],
    ['bg-trace-3000-dark', 'bg-red-500'],

    ['bg-secondary-3000-dark', 'bg-red-500'],
    ['bg-secondary-3000-hover-dark', 'bg-red-500'],
    ['bg-border-3000-dark', 'bg-red-500'],
    ['bg-border-bold-3000-dark', 'bg-red-500'],
    ['bg-glass-bg-3000-dark', 'bg-red-500'],
    ['bg-glass-border-3000-dark', 'bg-red-500'],
    ['bg-link-3000-dark', 'bg-red-500'],

    ['bg-secondary-3000-frame-bg-dark', 'bg-red-500'],
    ['bg-secondary-3000-button-bg-dark', 'bg-red-500'],
    ['bg-secondary-3000-button-border-dark', 'bg-red-500'],
    ['bg-secondary-3000-button-border-hover-dark', 'bg-red-500'],

    ['bg-danger-3000-frame-bg-dark', 'bg-red-500'],
    ['bg-danger-3000-button-border-dark', 'bg-red-500'],
    ['bg-danger-3000-button-border-hover-dark', 'bg-red-500'],

    // The derived colors
    // `--default` is a pre-3000 alias for "default text color" (`--text-3000` now)
    ['bg-default', 'bg-red-500'],
    ['bg-text-3000', 'bg-red-500'],
    ['bg-text-secondary-3000', 'bg-red-500'],
    ['bg-muted-3000', 'bg-red-500'],
    ['bg-primary-3000', 'bg-red-500'],
    ['bg-secondary-3000', 'bg-red-500'],
    ['bg-secondary-3000-hover', 'bg-red-500'],
]

const dataColors = [
    'data-color-1',
    'data-color-2',
    'data-color-3',
    'data-color-4',
    'data-color-5',
    'data-color-6',
    'data-color-7',
    'data-color-8',
    'data-color-9',
    'data-color-10',
    'data-color-11',
    'data-color-12',
    'data-color-13',
    'data-color-14',
    'data-color-15',
]

export function ColorPalette(): JSX.Element {
    const [hover, setHover] = useState<string>()
    return (
        <div className="flex flex-wrap items-start gap-4">
            {Object.keys(colorGroups).map((group) => (
                <div key={group} className="h-50 flex w-40 flex-col">
                    <div className="mb-2 text-ellipsis font-bold">{group}</div>
                    <div className="flex flex-1 flex-col overflow-hidden rounded-lg">
                        {colorGroups[group as keyof typeof colorGroups].map((color: string) => (
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
                        return (
                            <div className="relative h-8 w-8">
                                <div className={`${color as string} absolute inset-0 z-20 rounded border`} />
                                <div className="absolute inset-0 z-10 flex items-center justify-center">🦔</div>
                            </div>
                        )
                    },
                },
            ]}
        />
    )
}

export function AllThreeThousandColorOptions(): JSX.Element {
    return (
        <LemonTable
            dataSource={threeThousand.map((color) => ({ name: color, color }))}
            columns={[
                {
                    title: 'Class name',
                    key: 'name',
                    dataIndex: 'name',
                    render: function RenderName(name) {
                        if (!name) {
                            return ''
                        }
                        return `${name[0]}/${name[1]}`
                    },
                },
                {
                    title: 'Light mode',
                    key: 'light',
                    dataIndex: 'color',
                    render: function RenderColor(colorOldNew) {
                        return (
                            <div className="flex gap-2">
                                {colorOldNew &&
                                    colorOldNew.map((color) => (
                                        <div key={color} className={`${color} h-8 w-8 rounded border`} />
                                    ))}
                            </div>
                        )
                    },
                },
                {
                    title: 'Dark mode',
                    key: 'dark',
                    dataIndex: 'color',
                    render: function RenderColor(colorOldNew) {
                        return (
                            <div className="bg-primary-dark flex h-16 w-16 items-center justify-center rounded border">
                                {colorOldNew &&
                                    colorOldNew.map((color) => (
                                        <div key={color} className={`${color} h-8 w-8 rounded border`} />
                                    ))}
                            </div>
                        )
                    },
                },
            ]}
        />
    )
}

export function DataColors(): JSX.Element {
    return (
        <LemonTable
            dataSource={dataColors.map((color) => ({ name: color, color }))}
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
                            <div className="bg-primary-light flex h-16 w-16 items-center justify-center rounded border">
                                <div
                                    className="h-8 w-8 rounded border"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: `var(--${color})` }}
                                />
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
                            <div className="bg-primary-dark flex h-16 w-16 items-center justify-center rounded border">
                                <div
                                    className="h-8 w-8 rounded border"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: `var(--${color})` }}
                                />
                            </div>
                        )
                    },
                },
            ]}
        />
    )
}
