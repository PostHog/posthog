import type { Meta, StoryObj } from '@storybook/react'

import { CatalogExplainer } from './CatalogExplainer'

const meta: Meta<typeof CatalogExplainer> = {
    title: 'Data catalog/Catalog explainer',
    component: CatalogExplainer,
    parameters: { viewMode: 'story' },
    render: () => (
        <div className="@container w-240 p-4">
            <CatalogExplainer />
        </div>
    ),
}
export default meta

export const Open: StoryObj<typeof CatalogExplainer> = {}
