import type { Meta, StoryObj } from '@storybook/react'

import 'lib/components/DotMatrix/DotMatrix.scss'

import { ProductUsageFirstUseStar } from './ProductUsageFirstUseStar'

const meta: Meta<typeof ProductUsageFirstUseStar> = {
    title: 'Customer analytics/Product activity/First use star',
    component: ProductUsageFirstUseStar,
    args: { color: 'var(--color-orange-500)', label: 'First use ever' },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
export const FirstUse: StoryObj<typeof meta> = {}
