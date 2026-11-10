import type { Meta, StoryObj } from '@storybook/react'

import { LemonDialog } from '@posthog/lemon-ui'

import { getBreakingColumnChangeDialogProps } from './BreakingColumnChangeDialog'

const meta: Meta<typeof LemonDialog> = {
    title: 'Scenes/Data Warehouse/Breaking Column Change Dialog',
    component: LemonDialog,
    parameters: {
        layout: 'centered',
    },
}

export default meta
type Story = StoryObj<typeof LemonDialog>

export const Default: Story = {
    render: () => (
        <div className="w-[32rem] max-w-full">
            <LemonDialog
                {...getBreakingColumnChangeDialogProps(
                    {
                        removedColumns: ['legacy_planet_id'],
                        affectedViews: ['daily_planet_sales', 'moon_base_summary', 'rocket_cost_rollup'],
                        affectedViewCount: 5,
                        hasHiddenAffectedViews: true,
                    },
                    () => {},
                    () => {}
                )}
                inline
            />
        </div>
    ),
}
