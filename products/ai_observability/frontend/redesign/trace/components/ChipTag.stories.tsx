import type { Meta, StoryObj } from '@storybook/react'

import { IconCheck, IconX } from '@posthog/icons'

import { ChipTag } from './ChipTag'

const meta: Meta<typeof ChipTag> = {
    title: 'Scenes-App/AI observability/Trace view/Chip tag',
    component: ChipTag,
}
export default meta

type Story = StoryObj<typeof ChipTag>

function EveryType(): JSX.Element {
    return (
        <div className="flex gap-1.5">
            <ChipTag weight="normal">Default</ChipTag>
            <ChipTag weight="normal" type="danger" icon={<IconX />}>
                Evals 2/5 passed
            </ChipTag>
            <ChipTag weight="normal" type="success" icon={<IconCheck />}>
                Evals 5/5 passed
            </ChipTag>
            <ChipTag weight="normal" type="caution">
                Outliers
            </ChipTag>
        </div>
    )
}

export const OnPageAndDrawer: Story = {
    render: () => (
        <div className="flex flex-col">
            <div className="bg-primary p-2">
                <EveryType />
            </div>
            <div className="bg-surface-primary p-2">
                <EveryType />
            </div>
        </div>
    ),
}
