import { Meta, StoryObj } from '@storybook/react'
import { BreakdownTag as BreakdownTagComponent } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'

import { LemonTag as LemonTagComponent, LemonTagType } from './LemonTag'

const meta: Meta<typeof LemonTagComponent> = {
    title: 'Lemon UI/Lemon Tag',
    component: LemonTagComponent,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof LemonTagComponent>

const ALL_COLORS: LemonTagType[] = [
    'primary',
    'option',
    'highlight',
    'warning',
    'danger',
    'success',
    'default',
    'muted',
    'completion',
    'caution',
    'none',
]

export const LemonTag: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            {ALL_COLORS.map((type) => (
                <LemonTagComponent key={type} type={type}>
                    {type}
                </LemonTagComponent>
            ))}
        </div>
    ),
}

export const BreakdownTag: Story = {
    render: () => (
        <>
            <BreakdownTagComponent breakdownType="event" breakdown="$browser" />
            <div className="mt-1" />
            <BreakdownTagComponent breakdownType="hogql" breakdown="$properties.browser" />
            <div className="mt-1" />
            <BreakdownTagComponent breakdownType="cohort" breakdown={1} />
        </>
    ),
}
