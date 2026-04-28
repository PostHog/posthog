import { Meta, StoryObj } from '@storybook/react'

import { HighlightedJSONViewer } from './HighlightedJSONViewer'
import { JSONViewer } from './JSONViewer'

const meta: Meta = {
    title: 'Components/JSONViewer',
}
export default meta

type Story = StoryObj

const nestedObject = {
    company: {
        id: 'lettuce-9876-spinach-5432',
        name: 'Veggie Inc.',
        geo: {
            city: 'Vegville',
            state: 'Greensylvania',
            country: 'Vegetaria',
            postalCode: '12345',
            streetAddress: '101 Kale Avenue',
        },
        site: {
            phoneNumbers: ['+1 555-CABBAGE'],
            emailAddresses: ['info@veggie.ai'],
        },
    },
}

export const SimpleObject: Story = {
    render: () => <JSONViewer src={{ name: 'Veggie Inc.', count: 42, active: true, owner: null }} />,
}

export const NestedObject: Story = {
    render: () => <JSONViewer src={nestedObject} collapsed={1} />,
}

export const ArrayOfStrings: Story = {
    render: () => <JSONViewer src={['us', 'eu', 'apac']} />,
}

export const HighlightedWithSearch: Story = {
    render: () => <HighlightedJSONViewer src={nestedObject} searchQuery="email" collapsed={2} />,
}
