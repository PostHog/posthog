import { Marker } from 'maplibre-gl'

import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { personLogic } from 'scenes/persons/personLogic'
import { useValues } from 'kea'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { NotFound } from 'lib/components/NotFound'
import { Map } from '../../../lib/components/Map/Map'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeEmptyState } from './components/NotebookNodeEmptyState'
import { NotebookNodeProps, NotebookNodeType } from '../types'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeMapAttributes>): JSX.Element | null => {
    const { id } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    const logic = personLogic({ id })
    const { person, personLoading } = useValues(logic)

    if (personLoading) {
        return <LemonSkeleton className="h-6" />
    } else if (!person) {
        return <NotFound object="person" />
    }

    if (!expanded) {
        return null
    }

    const longtitude = person?.properties?.['$geoip_longitude']
    const latitude = person?.properties?.['$geoip_latitude']
    const personCoordinates: [number, number] | null =
        !isNaN(longtitude) && !isNaN(latitude) ? [longtitude, latitude] : null

    if (!personCoordinates) {
        return <NotebookNodeEmptyState message="No map available." />
    }

    return (
        <Map
            center={personCoordinates}
            markers={[new Marker({ color: 'var(--color-accent)' }).setLngLat(personCoordinates)]}
            className="h-full"
        />
    )
}

type NotebookNodeMapAttributes = {
    id: string
}

export const NotebookNodeMap = createPostHogWidgetNode<NotebookNodeMapAttributes>({
    nodeType: NotebookNodeType.Map,
    titlePlaceholder: 'Location',
    Component,
    resizeable: true,
    heightEstimate: 150,
    expandable: true,
    startExpanded: true,
    attributes: {
        id: {},
    },
})
