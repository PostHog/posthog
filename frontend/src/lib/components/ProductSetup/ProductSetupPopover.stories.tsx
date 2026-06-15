import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { mswDecorator } from '~/mocks/browser'
import { ProductKey } from '~/queries/schema/schema-general'

import { ProductSetupPopover, ProductSetupPopoverProps } from './ProductSetupPopover'

const meta: Meta<ProductSetupPopoverProps> = {
    title: 'Components/ProductSetup/ProductSetupPopover',
    component: ProductSetupPopover,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    created_at: new Date().toISOString(),
                },
            },
            patch: {
                '/api/environments/@current/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<ProductSetupPopoverProps>

export const Default: Story = {
    render: () => {
        const [visible, setVisible] = useState(true)
        const [product, setProduct] = useState(ProductKey.PRODUCT_ANALYTICS)

        return (
            <div className="p-4 w-200 h-200 bg-white flex items-start justify-end">
                <ProductSetupPopover
                    visible={visible}
                    onClickOutside={() => setVisible(false)}
                    selectedProduct={product}
                    onSelectProduct={setProduct}
                >
                    <LemonButton type="primary" onClick={() => setVisible(!visible)}>
                        Quick start
                    </LemonButton>
                </ProductSetupPopover>
            </div>
        )
    },
}
