import { Meta, StoryObj } from '@storybook/react'

import { NewInsightMenuOverlay } from './NewInsightMenu'
import { NewInsightPickerVariant } from './newInsightMenuPrototypes'

const meta: Meta<typeof NewInsightMenuOverlay> = {
    title: 'Scenes-App/Saved Insights/New Insight Menu',
    component: NewInsightMenuOverlay,
}
export default meta

type Story = StoryObj<typeof NewInsightMenuOverlay>

function renderVariant(variant: NewInsightPickerVariant): JSX.Element {
    return (
        <div className="border border-primary rounded bg-surface-primary w-fit p-1">
            <NewInsightMenuOverlay variant={variant} />
        </div>
    )
}

export const FlatGrid: Story = { render: () => renderVariant('A') }
export const VariantChips: Story = { render: () => renderVariant('B') }
export const GroupedByQuestion: Story = { render: () => renderVariant('C') }
export const GridWithPresets: Story = { render: () => renderVariant('D') }
export const TwoStep: Story = { render: () => renderVariant('E') }
export const GroupedTwoColumns: Story = { render: () => renderVariant('F') }
