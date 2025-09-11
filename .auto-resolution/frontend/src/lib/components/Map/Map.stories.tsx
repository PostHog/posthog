import type { Meta, StoryObj } from '@storybook/react'

import { Map } from './Map'

const coordinates: [number, number] = [0.119167, 52.205276]

const meta: Meta<typeof Map> = {
    title: 'Components/Map',
    component: Map,
    tags: ['autodocs', 'test-skip'],
    // :TRICKY: We can't use markers in Storybook stories, as the Marker class is
    // not JSON-serializable (circular structure).
    args: {
        center: coordinates,
        className: 'h-60',
    },
}
type Story = StoryObj<typeof Map>

export const Basic: Story = {}

export default meta
