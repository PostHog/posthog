import { Meta } from '@storybook/react'
import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const meta: Meta = {
    title: 'UI/Colors',
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

const stepsNeutral = [25, 50, 100, 250, 350, 400, 450, 500]
const steps = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

const primtiveColorMap: Map<string, number[]> = new Map([
    ['color-posthog-3000', stepsNeutral],
    ['color-neutral', steps],
    ['color-neutral-cool', steps],

    // Tailwind colors
    ['color-red', steps],
    ['color-orange', steps],
    ['color-amber', steps],
    ['color-yellow', steps],
    ['color-lime', steps],
    ['color-green', steps],
    ['color-emerald', steps],
    ['color-teal', steps],
    ['color-cyan', steps],
    ['color-sky', steps],
    ['color-blue', steps],
    ['color-indigo', steps],
    ['color-violet', steps],
    ['color-purple', steps],
    ['color-fuchsia', steps],
    ['color-pink', steps],
    ['color-rose', steps],
    ['color-slate', steps],
    ['color-gray', steps],
    ['color-zinc', steps],
    ['color-neutral', steps],
    ['color-stone', steps],
])

export function PrimitiveColors(): JSX.Element {
    return (
        <div className="flex gap-4 flex-wrap items-start">
            {Array.from(primtiveColorMap.entries()).map(([colorName, steps]) => (
                <div key={colorName} className="flex flex-col gap-1">
                    <div className="text-primary font-medium">{colorName}</div>
                    <div className="flex flex-col gap-1">
                        {steps.map((step) => (
                            <div key={step} className="flex items-center gap-2">
                                <div
                                    className="w-12 h-8 rounded border border-primary"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: `var(--${colorName}-${step})` }}
                                />
                                <div className="text-sm text-primary">{step}</div>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

export function BrandAccentColors(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [primaryHue, setPrimaryHue] = useState<number>(isDarkModeOn ? 43 : 19)
    const [primarySaturation, setPrimarySaturation] = useState<number>(isDarkModeOn ? 94 : 100)
    const [primaryLightness, setPrimaryLightness] = useState<number>(isDarkModeOn ? 57 : 48)

    useEffect(() => {
        document.body.style.setProperty(
            '--color-accent',
            `hsl(${primaryHue}deg ${primarySaturation}% ${primaryLightness}%)`
        )
    }, [primaryHue, primarySaturation, primaryLightness])

    return (
        <div className="flex flex-col gap-4">
            <div className="border border-primary flex flex-col gap-2 p-4 items-start">
                <p className="text-accent">Accent</p>
            </div>

            <div className="flex flex-col gap-2 border border-primary rounded-md p-2">
                <div className="text-primary font-medium">Primary accent color</div>

                <div className="flex gap-2">
                    <label className="flex flex-col gap-1 flex-1">
                        <label htmlFor="primary-hue">Hue</label>
                        <LemonSlider value={primaryHue} onChange={setPrimaryHue} min={0} max={360} />
                    </label>
                    <label className="flex flex-col gap-1 flex-1">
                        <label htmlFor="primary-saturation">Saturation</label>
                        <LemonSlider value={primarySaturation} onChange={setPrimarySaturation} min={0} max={100} />
                    </label>
                    <label className="flex flex-col gap-1 flex-1">
                        <label htmlFor="primary-lightness">Lightness</label>
                        <LemonSlider value={primaryLightness} onChange={setPrimaryLightness} min={0} max={100} />
                    </label>

                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: `var(--color-accent)` }}
                        className="w-12 h-12 rounded border border-primary"
                    />
                </div>
            </div>
        </div>
    )
}

interface RenderColorConfig {
    tailwindClass?: string
    description: string
    name: string
}

function RenderTable({ colors }: { colors: RenderColorConfig[] }): JSX.Element {
    const gridClasses = 'grid grid-cols-[100px_1fr_1fr_1fr] gap-2 [&_p]:mb-0 [&_pre]:mb-0 items-center'
    return (
        <div className="flex flex-col gap-2">
            <div className={gridClasses}>
                <p>&nbsp;</p>
                <p>Name</p>
                <p>Tailwind class</p>
                <p>Description</p>
            </div>
            {colors.map(({ tailwindClass, description, name }) => {
                return (
                    <div key={name} className={gridClasses}>
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div className="rounded h-full w-full" style={{ backgroundColor: `var(${name})` }}>
                            &nbsp;
                        </div>
                        <pre className="rounded border border-primary p-2 text-sm">{name}</pre>
                        <pre className="rounded border border-primary p-2 text-sm">{tailwindClass}</pre>
                        <p className="!mb-0 text-xs">{description}</p>
                    </div>
                )
            })}
        </div>
    )
}

export function SemanticColors(): JSX.Element {
    const textColors: RenderColorConfig[] = [
        {
            tailwindClass: 'text-primary',
            description: 'the main text color',
            name: '--color-text-primary',
        },
        {
            tailwindClass: 'text-primary-inverse',
            description: 'the main text color on a inverted background',
            name: '--color-text-primary-inverse',
        },
        {
            tailwindClass: 'text-secondary',
            description: 'a more subtle text color',
            name: '--color-text-secondary',
        },
        {
            tailwindClass: 'text-tertiary',
            description: 'most subtle text color',
            name: '--color-text-tertiary',
        },
        // {
        //     tailwindClass: 'text-accent',
        //     description: 'the main accent text color',
        //     variableName: '--color-accent'
        // },
        // {
        //     tailwindClass: 'text-accent-hover',
        //     description: 'the main accent text color on hover',
        //     variableName: '--color-accent-hover'
        // },
        // {
        //     tailwindClass: 'text-accent-active',
        //     description: 'the main accent text color on active',
        //     variableName: '--color-accent-active'
        // },
        // {
        //     tailwindClass: 'text-accent-highlight-secondary',
        //     description: 'the main accent text color on highlight',
        //     variableName: '--color-accent-highlight-secondary'
        // },
        // {
        //     tailwindClass: 'text-accent-secondary',
        //     description: 'the secondary accent text color',
        //     variableName: '--color-accent-secondary'
        // },
        // {
        //     tailwindClass: 'text-accent-secondary-hover',
        //     description: 'the secondary accent text color on hover',
        //     variableName: '--color-accent-secondary-hover'
        // },
        // {
        //     tailwindClass: 'text-accent-secondary-active',
        //     description: 'the secondary accent text color on active',
        //     variableName: '--color-accent-secondary-active'
        // },
        // {
        //     tailwindClass: 'text-accent-secondary-highlight',
        //     description: 'the secondary accent text color on highlight',
        //     variableName: '--color-accent-secondary-highlight'
        // }
    ]
    const backgroundColors: RenderColorConfig[] = [
        {
            tailwindClass: 'bg-primary',
            description:
                'the main background color, use behind everything, or on something to fade into the background',
            name: '--color-bg-primary',
        },
    ]
    const surfaceColors: RenderColorConfig[] = [
        {
            tailwindClass: 'bg-surface-primary',
            description: 'the most prominent area on the screen (after tooltip)',
            name: '--color-bg-surface-primary',
        },
        {
            tailwindClass: 'bg-surface-secondary',
            description: 'the second most prominent area on the screen',
            name: '--color-bg-surface-secondary',
        },
        {
            tailwindClass: 'bg-surface-tertiary',
            description: 'the least prominent area on the screen',
            name: '--color-bg-surface-tertiary',
        },
        {
            tailwindClass: 'bg-surface-tooltip',
            description: 'the tooltip surface color',
            name: '--color-bg-surface-tooltip',
        },
        {
            tailwindClass: 'bg-surface-popover',
            description: 'the popover surface color',
            name: '--color-bg-surface-popover',
        },
    ]
    const fillColors: RenderColorConfig[] = [
        {
            tailwindClass: 'bg-fill-primary',
            description: 'the main fill color',
            name: '--color-bg-fill-primary',
        },
        {
            tailwindClass: 'bg-fill-info-secondary',
            description: 'the main fill color on an info fill',
            name: '--color-bg-fill-info-secondary',
        },
        {
            tailwindClass: 'bg-fill-warning-secondary',
            description: 'the main fill color on a warning fill',
            name: '--color-bg-fill-warning-secondary',
        },
        {
            tailwindClass: 'bg-fill-warning-tertiary',
            description: 'the warning tertiary fill color',
            name: '--color-bg-fill-warning-tertiary',
        },
        {
            tailwindClass: 'bg-fill-warning-highlight',
            description: 'the warning highlight fill color',
            name: '--color-bg-fill-warning-highlight',
        },
        {
            tailwindClass: 'bg-fill-error-secondary',
            description: 'the main fill color on an error fill',
            name: '--color-bg-fill-error-secondary',
        },
        {
            tailwindClass: 'bg-fill-error-tertiary',
            description: 'the error tertiary fill color',
            name: '--color-bg-fill-error-tertiary',
        },
        {
            tailwindClass: 'bg-fill-error-highlight',
            description: 'the error highlight fill color',
            name: '--color-bg-fill-error-highlight',
        },
        {
            tailwindClass: 'bg-fill-success-secondary',
            description: 'the main fill color on a success fill',
            name: '--color-bg-fill-success-secondary',
        },
        {
            tailwindClass: 'bg-fill-success-highlight',
            description: 'the success highlight fill color',
            name: '--color-bg-fill-success-highlight',
        },
        {
            tailwindClass: 'bg-fill-success-tertiary',
            description: 'the success tertiary fill color',
            name: '--color-bg-fill-success-tertiary',
        },
        {
            tailwindClass: 'bg-fill-input',
            description: 'the input fill color',
            name: '--color-bg-fill-input',
        },
        {
            tailwindClass: 'bg-fill-info-tertiary',
            description: 'the info tertiary fill color',
            name: '--color-bg-fill-info-tertiary',
        },
    ]

    const borderColors: RenderColorConfig[] = [
        {
            tailwindClass: 'border-primary',
            description: 'the primary border color',
            name: '--color-border-primary',
        },
        {
            tailwindClass: 'border-info',
            description: 'the info border color',
            name: '--color-border-info',
        },
        {
            tailwindClass: 'border-warning',
            description: 'the warning border color',
            name: '--color-border-warning',
        },
        {
            tailwindClass: 'border-error',
            description: 'the error border color',
            name: '--color-border-error',
        },
        {
            tailwindClass: 'border-success',
            description: 'the success border color',
            name: '--color-border-success',
        },
    ]
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4 border border-primary rounded-md p-2 bg-fill-primary">
                <div className="deprecated-space-y-0">
                    <h2>Texts</h2>
                    <p>
                        Texts are used to display content on the screen. They can be used to display text, icons, and
                        other content.
                    </p>
                </div>
                <RenderTable colors={textColors} />
            </div>
            <div className="flex flex-col gap-4 border border-primary rounded-md p-2 bg-fill-primary">
                <div className="deprecated-space-y-0">
                    <h2>Backgrounds</h2>
                    <p>Behind surfaces, large areas: app scenes, etc.</p>
                </div>
                <RenderTable colors={backgroundColors} />
            </div>
            <div className="flex flex-col gap-4 border border-primary rounded-md p-2 bg-fill-primary">
                <div className="deprecated-space-y-0">
                    <h2>Surfaces</h2>
                    <p>
                        Above backgrounds, smaller areas: Cards, Tables, stuff that stands out on top of the background.
                    </p>
                </div>
                <RenderTable colors={surfaceColors} />
            </div>
            <div className="flex flex-col gap-4 border border-primary rounded-md p-2 bg-fill-primary">
                <div className="deprecated-space-y-0">
                    <h2>Fills</h2>
                    <p>Small colourful areas: banners, pills, buttons, etc.</p>
                </div>
                <RenderTable colors={fillColors} />
            </div>
            <div className="flex flex-col gap-4 border border-primary rounded-md p-2 bg-fill-primary">
                <div className="deprecated-space-y-0">
                    <h2>Borders</h2>
                    <p>Borders for surfaces/fills</p>
                </div>
                <RenderTable colors={borderColors} />
            </div>
        </div>
    )
}
