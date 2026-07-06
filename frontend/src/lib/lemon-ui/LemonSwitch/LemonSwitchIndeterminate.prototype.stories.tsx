/**
 * PROTOTYPE — throwaway stories for LemonSwitchIndeterminate.prototype.tsx.
 * Run with `pnpm storybook`, open "Lemon UI/Lemon Switch/Indeterminate Prototype".
 * Delete together with the prototype file once a variant wins.
 */
import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import {
    PrototypeSwitchProps,
    PrototypeToggleValue,
    VariantACenteredHandle,
    VariantBDashInHandle,
    VariantCHalfFill,
    VariantDFullWidthHandleDash,
    VariantENoHandleDash,
    VariantFNoHandleDashFillGray,
    VariantGCenteredHandleDash,
} from './LemonSwitchIndeterminate.prototype'

const meta: Meta = {
    title: 'Lemon UI/Lemon Switch/Indeterminate Prototype',
    tags: ['test-skip'],
}
export default meta

// Ordered by mechanism: handle-only treatments, then dash-in-handle, then dash-without-handle.
const VARIANTS: {
    key: string
    name: string
    description: string
    Component: (props: PrototypeSwitchProps) => JSX.Element
}[] = [
    {
        key: 'A',
        name: 'Centered handle',
        description: 'Handle parks mid-track on a neutral track. Position alone signals "mixed".',
        Component: VariantACenteredHandle,
    },
    {
        key: 'C',
        name: 'Half fill',
        description: 'Handle stretches over the left half, right half shows accent. Literally half on.',
        Component: VariantCHalfFill,
    },
    {
        key: 'B',
        name: 'Dash in handle',
        description:
            'Track filled like "checked", handle carries a minus glyph — borrowed from indeterminate checkboxes.',
        Component: VariantBDashInHandle,
    },
    {
        key: 'G',
        name: 'Centered half-width handle with dash',
        description:
            'A + B + C combined: half-width handle parks mid-track and carries the minus glyph on a "checked"-filled track.',
        Component: VariantGCenteredHandleDash,
    },
    {
        key: 'D',
        name: 'Full-width handle with dash',
        description: 'Handle stretches across the entire track and carries the minus glyph. No position to misread.',
        Component: VariantDFullWidthHandleDash,
    },
    {
        key: 'E',
        name: 'Dash on track, no handle',
        description: 'No handle at all — a gray (border-colored) track shows a centered dash. Most minimal treatment.',
        Component: VariantENoHandleDash,
    },
    {
        key: 'F',
        name: 'Dash on track, no handle (fill gray)',
        description: 'Like E, but the track keeps the regular unchecked switch fill gray instead of the border gray.',
        Component: VariantFNoHandleDashFillGray,
    },
]

function VariantRow({ variant }: { variant: (typeof VARIANTS)[number] }): JSX.Element {
    const [value, setValue] = useState<PrototypeToggleValue>('indeterminate')
    const { Component } = variant
    return (
        <div className="flex flex-col gap-2 p-4 border rounded bg-surface-primary">
            <div className="flex items-center justify-between">
                <div>
                    <div className="font-semibold">
                        {variant.key} — {variant.name}
                    </div>
                    <div className="text-secondary text-xs">{variant.description}</div>
                </div>
                <LemonButton size="xsmall" type="secondary" onClick={() => setValue('indeterminate')}>
                    Reset to indeterminate
                </LemonButton>
            </div>
            <div className="flex items-center gap-8">
                <Component label="Interactive (click me)" value={value} onChange={setValue} />
            </div>
            <div className="flex items-center gap-8 text-xs text-secondary">
                <Component label="Unchecked" value={false} onChange={() => {}} />
                <Component label="Indeterminate" value="indeterminate" onChange={() => {}} />
                <Component label="Checked" value={true} onChange={() => {}} />
            </div>
        </div>
    )
}

export const AllVariants: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-4 max-w-160">
            <p className="text-sm text-secondary m-0">
                Prototype: three treatments for an indeterminate LemonSwitch state. Clicking an indeterminate switch
                resolves it to checked; after that it toggles normally.
            </p>
            {VARIANTS.map((variant) => (
                <VariantRow key={variant.key} variant={variant} />
            ))}
        </div>
    ),
}
