import { Meta, StoryObj } from '@storybook/react'
import { BreakdownTag as BreakdownTagComponent } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'

const meta: Meta<typeof BreakdownTagComponent> = {
    title: 'Filters/Breakdown Tag',
    component: BreakdownTagComponent,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof BreakdownTagComponent>

export const BreakdownTag: Story = {
    render: () => (
        <>
            <BreakdownTagComponent breakdownType="event" breakdown="$browser" />
            <div className="mt-1" />
            <BreakdownTagComponent breakdownType="hogql" breakdown="$properties.browser" />
            <div className="mt-1" />
            <BreakdownTagComponent breakdownType="cohort" breakdown={1} />
            <div className="mt-1" />
            <BreakdownTagComponent breakdownType="cohort" breakdown="coalesce(null, 1, 2) -- some sql" />
            <div className="mt-1" />
            <BreakdownTagComponent breakdownType="event" breakdown="$browser" size="small" />
        </>
    ),
}
