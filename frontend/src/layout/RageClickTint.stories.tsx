import { Meta, StoryObj } from '@storybook/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { RageClickTint } from './RageClickTint'
import { rageClickTintLogic } from './rageClickTintLogic'

const meta: Meta<typeof RageClickTint> = {
    title: 'Layout/RageClickTint',
    component: RageClickTint,
    parameters: { layout: 'fullscreen' },
}
export default meta

type Story = StoryObj<typeof RageClickTint>

export const Default: Story = {
    render: () => (
        <div className="min-h-screen bg-primary p-8 text-default">
            <h1>Rageclick tint</h1>
            <p>Each rageclick adds a little red. After five seconds, the tint gradually fades.</p>
            <LemonButton type="primary" onClick={() => rageClickTintLogic.actions.rageClick()}>
                Simulate a rageclick
            </LemonButton>
            <RageClickTint />
        </div>
    ),
}
