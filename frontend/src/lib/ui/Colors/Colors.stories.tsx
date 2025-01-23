import { Meta } from '@storybook/react'
import { useValues } from 'kea'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { useEffect, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const meta: Meta = {
    title: 'Design System/Colors',
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

const steps3000 = [25, 50, 100, 250, 350, 400, 450, 500]
const steps = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

const primtiveColorMap: Map<string, number[]> = new Map([
    ['primitive-3000', steps3000],
    ['primitive-neutral-cool', steps],
    // ['primitive-gray', steps],
    // ['primitive-zinc', steps],
    ['primitive-stone', steps],
    ['primitive-red', steps],
    ['primitive-orange', steps],
    ['primitive-amber', steps],
    ['primitive-yellow', steps],
    ['primitive-lime', steps],
    ['primitive-green', steps],
    ['primitive-emerald', steps],
    ['primitive-teal', steps],
    ['primitive-cyan', steps],
    ['primitive-sky', steps],
    ['primitive-blue', steps],
    ['primitive-indigo', steps],
    ['primitive-violet', steps],
    ['primitive-purple', steps],
    ['primitive-fuchsia', steps],
    ['primitive-pink', steps],
    ['primitive-rose', steps],
])

export function PrimitiveColors(): JSX.Element {
    return (
        <div className="flex gap-4 flex-wrap items-start">
            {Array.from(primtiveColorMap.entries()).map(([colorName, steps]) => (
                <div key={colorName} className="flex flex-col gap-1">
                    <div className="content-primary font-medium">{colorName}</div>
                    <div className="flex flex-col gap-1">
                        {steps.map((step) => (
                            <div key={step} className="flex items-center gap-2">
                                <div
                                    className="w-12 h-8 rounded border border-border"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: `var(--${colorName}-${step})` }}
                                />
                                <div className="text-sm content-primary">{step}</div>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

export function BrandColors(): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [primaryHue, setPrimaryHue] = useState<number>(isDarkModeOn ? 43 : 19)
    const [primarySaturation, setPrimarySaturation] = useState<number>(isDarkModeOn ? 94 : 100)
    const [primaryLightness, setPrimaryLightness] = useState<number>(isDarkModeOn ? 57 : 48)

    const [secondaryHue, setSecondaryHue] = useState<number>(228)
    const [secondarySaturation, setSecondarySaturation] = useState<number>(100)
    const [secondaryLightness, setSecondaryLightness] = useState<number>(56)

    useEffect(() => {
        document.body.style.setProperty(
            '--accent-primary',
            `hsl(${primaryHue}deg ${primarySaturation}% ${primaryLightness}%)`
        )
        document.body.style.setProperty(
            '--accent-secondary',
            `hsl(${secondaryHue}deg ${secondarySaturation}% ${secondaryLightness}%)`
        )
    }, [primaryHue, primarySaturation, primaryLightness, secondaryHue, secondarySaturation, secondaryLightness])

    return (
        <div className="flex flex-col gap-4">
            <div className="border border-border flex flex-col gap-2 p-4 items-start">
                <p className="text-accent-primary">Accent primary</p>
                <p className="text-accent-secondary">Accent secondary</p>
            </div>

            <div className="flex flex-col gap-2 border border-border rounded-md p-2">
                <div className="content-primary font-medium">Primary accent color</div>

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
                        style={{ backgroundColor: `var(--accent-primary)` }}
                        className="w-12 h-12 rounded border border-border"
                    />
                </div>
            </div>

            <div className="flex flex-col gap-2 border border-border rounded-md p-2">
                <div className="content-primary font-medium">Secondary accent color</div>
                <div className="flex gap-2">
                    <label className="flex flex-col gap-1 flex-1">
                        <label htmlFor="secondary-hue">Hue</label>
                        <LemonSlider value={secondaryHue} onChange={setSecondaryHue} min={0} max={360} />
                    </label>
                    <label className="flex flex-col gap-1 flex-1">
                        <label htmlFor="secondary-saturation">Saturation</label>
                        <LemonSlider value={secondarySaturation} onChange={setSecondarySaturation} min={0} max={100} />
                    </label>
                    <label className="flex flex-col gap-1 flex-1">
                        <label htmlFor="secondary-lightness">Lightness</label>
                        <LemonSlider value={secondaryLightness} onChange={setSecondaryLightness} min={0} max={100} />
                    </label>

                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: `var(--accent-secondary)` }}
                        className="w-12 h-12 rounded border border-border"
                    />
                </div>
            </div>
        </div>
    )
}

export function SemanticColors(): JSX.Element {
    const textColors = ['text-primary']
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2 border border-border rounded-md p-2">
                <h2>Texts</h2>
                {textColors.map((color) => (
                    <div key={color} className="flex items-center gap-2">
                        <p className={`w-12 h-12 rounded border border-border ${color}`}>{color}</p>
                    </div>
                ))}
            </div>
        </div>
    )
}
