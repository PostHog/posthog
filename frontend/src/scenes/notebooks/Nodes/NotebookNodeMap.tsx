import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { Marker } from 'maplibre-gl'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps } from 'scenes/notebooks/Notebook/utils'
import { personLogic } from 'scenes/persons/personLogic'

import { NotebookNodeType } from '~/types'

import { Map } from '../../../lib/components/Map/Map'
import { NotebookNodeEmptyState } from './components/NotebookNodeEmptyState'
import { notebookNodeLogic } from './notebookNodeLogic'

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
            markers={[new Marker({ color: 'var(--primary)' }).setLngLat(personCoordinates)]}
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
