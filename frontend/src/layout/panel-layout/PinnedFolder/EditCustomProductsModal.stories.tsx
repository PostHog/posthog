import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EditCustomProductsModal } from './EditCustomProductsModal'

const INITIAL_PRODUCTS = ['Dashboards', 'Session replay', 'Feature flags']

const meta: Meta<typeof EditCustomProductsModal> = {
    title: 'Layout/Pinned Folder/Edit Custom Products Modal',
    component: EditCustomProductsModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/user_product_list/': {
                    results: INITIAL_PRODUCTS.map((path, index) => ({
                        id: `product-${index}`,
                        product_path: path,
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                    })),
                },
                '/api/users/@me': {
                    ...MOCK_DEFAULT_USER,
                    allow_sidebar_suggestions: true,
                },
            },
        }),
    ],
}
export default meta
