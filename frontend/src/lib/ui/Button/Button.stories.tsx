import { Meta, Story } from '@storybook/react'

import { Button } from './Button'

const meta: Meta = {
    title: 'UI/Button',
}
export default meta

export const Default: Story = () => {
    return (
        <div className="flex flex-col gap-16 items-start surface-3000-primary">
            <Button>Default</Button>

            <Button intent="primary">Primary</Button>

            <Button intent="muted">Muted</Button>

            <Button intent="muted-darker">Muted Darker</Button>

            <div className="h-[42px] flex justify-between items-center gap-2 px-2 token-surface-3000-tertiary py-4">
                <Button intent="top-bar-tabs">Top Bar Tabs</Button>
            </div>
        </div>
    )
}
