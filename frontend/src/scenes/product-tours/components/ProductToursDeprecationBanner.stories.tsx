import type { Meta, StoryObj } from '@storybook/react'

import { ProductToursDeprecationBanner } from './ProductToursDeprecationBanner'

type Story = StoryObj<typeof ProductToursDeprecationBanner>

const meta: Meta<typeof ProductToursDeprecationBanner> = {
    title: 'Scenes-App/Product Tours/Deprecation banner',
    component: ProductToursDeprecationBanner,
}
export default meta

export const Default: Story = {}
