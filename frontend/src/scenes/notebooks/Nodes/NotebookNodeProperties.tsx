import { NotebookNodeType } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps } from '../Notebook/utils'
import { LemonLabel } from '@posthog/lemon-ui'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePropertiesAttributes>): JSX.Element => {
    const { nodeId } = attributes

    const person = {
        properties: {
            $geoip_city_name: 'Modena',
            $geoip_continent_code: 'EU',
            $geoip_continent_name: 'Europe',
            $geoip_country_code: 'IT',
            $geoip_country_name: 'Italy',
            $geoip_latitude: 44.6511,
            $geoip_longitude: 10.9211,
            $geoip_postal_code: '41124',
            $geoip_subdivision_1_code: '45',
            $geoip_subdivision_1_name: 'Emilia-Romagna',
            $geoip_subdivision_2_code: 'MO',
            $geoip_subdivision_2_name: 'Province of Modena',
            $geoip_time_zone: 'Europe/Rome',
        },
    }

    return (
        <div className="p-2">
            {Object.entries(person.properties).map(([key, value]) => (
                <div key={key}>
                    <LemonLabel>
                        <PropertyKeyInfo value={key} />
                    </LemonLabel>
                    <PropertiesTable properties={value} rootKey={key} />
                </div>
            ))}
        </div>
    )
}

type NotebookNodePropertiesAttributes = {}

export const NotebookNodeProperties = createPostHogWidgetNode<NotebookNodePropertiesAttributes>({
    nodeType: NotebookNodeType.Properties,
    titlePlaceholder: 'Properties',
    Component,
    resizeable: true,
    expandable: false,
    attributes: {},
})
