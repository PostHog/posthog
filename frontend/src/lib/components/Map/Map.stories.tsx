import type { Meta, StoryObj } from '@storybook/react'
import { Marker } from 'maplibre-gl'

import { Map, MapComponent } from './Map'

const meta: Meta<typeof Map> = {
    title: 'Components/Map',
    component: Map,
    tags: ['autodocs'],
}
type Story = StoryObj<typeof Map>

const coordinates: [number, number] = [0.119167, 52.205276]

export const Unavailable: Story = {}

export const Basic: Story = {
    render: (args) => (
        <MapComponent
            mapLibreStyleUrl="" // TODO: set this value for the publish storybook and visual regression tests
            {...args}
        />
    ),
    args: {
        center: coordinates,
        markers: [new Marker({ color: 'var(--primary)' }).setLngLat(coordinates)],
        className: 'h-60',
    },
}

export default meta
