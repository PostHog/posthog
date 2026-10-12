import type { Meta, StoryObj } from '@storybook/react'

import { ProductToursDeprecationBanner } from './ProductToursDeprecationBanner'

type Story = StoryObj<typeof ProductToursDeprecationBanner>

const meta: Meta<typeof ProductToursDeprecationBanner> = {
    title: 'Scenes-App/Product Tours/Deprecation banner',
    component: ProductToursDeprecationBanner,
    // LemonBanner is a CSS container, so it collapses unless its parent sets a width.
    decorators: [
        (Story) => (
            <div className="w-[32rem]">
                <Story />
            </div>
        ),
    ],
    parameters: { layout: 'padded' },
}
export default meta

export const Default: Story = {}
