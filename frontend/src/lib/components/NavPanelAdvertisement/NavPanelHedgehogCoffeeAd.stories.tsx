import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { DONATION_VARIANTS } from './NavPanelHedgehogCoffeeAd'

const meta = {
    title: 'Components/NavPanelHedgehogCoffee',
    parameters: { layout: 'padded' },
} satisfies Meta<typeof AdvertisementCard>

export default meta
type Story = StoryObj<typeof meta>

// Both cards a long-term free org can see, side by side - they alternate between donation windows,
// so only one is ever on screen in the real app. Rendered at the sidebar's own width.
export const BothVariants: Story = {
    render: (): JSX.Element => (
        <div className="flex flex-wrap items-start gap-4">
            {DONATION_VARIANTS.map((variant, index) => (
                <div key={variant.title} className="w-[232px]">
                    <div className="mb-1 font-mono text-xs text-muted">window {index + 1}</div>
                    <BindLogic
                        logic={navPanelAdvertisementLogic}
                        props={{ campaign: `story-hedgehog-coffee-w${index + 1}` }}
                    >
                        <AdvertisementCard title={variant.title} text={variant.text} hero={variant.hero} />
                    </BindLogic>
                </div>
            ))}
        </div>
    ),
}
