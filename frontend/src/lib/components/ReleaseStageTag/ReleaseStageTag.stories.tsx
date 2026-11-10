import type { Meta, StoryObj } from '@storybook/react'

import { ProductItemCategory } from '~/queries/schema/schema-general'

import { ReleaseStageTag } from './ReleaseStageTag'

type Story = StoryObj<typeof ReleaseStageTag>
const meta: Meta<typeof ReleaseStageTag> = {
    title: 'Components/ReleaseStageTag',
    component: ReleaseStageTag,
    parameters: {},
}
export default meta

export const Alpha: Story = {
    args: { product: { category: ProductItemCategory.ANALYTICS, tags: ['alpha'], flag: 'example-flag' } },
}

export const Beta: Story = {
    args: { product: { category: ProductItemCategory.ANALYTICS, tags: ['beta'] } },
}

export const Internal: Story = {
    args: { product: { category: ProductItemCategory.UNRELEASED, flag: 'example-flag' } },
}
