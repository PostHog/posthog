import { useActions } from 'kea'
import { useMemo } from 'react'

import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { Group, PropertyDefinitionType } from '~/types'

import { groupLogic } from '../groupLogic'

export function GroupPropertiesCard({ groupData }: { groupData: Group }): JSX.Element {
    const { editProperty } = useActions(groupLogic)
    const propertySummary = useMemo(() => {
        return Object.fromEntries(
            Object.entries(groupData.group_properties || {})
                .filter(([_, value]) => typeof value !== 'object' || value === null)
                .slice(0, 5)
        )
    }, [groupData.group_properties])

    return (
        <div className="flex flex-col gap-2">
            <PropertiesTable
                type={PropertyDefinitionType.Group}
                properties={propertySummary || {}}
                onEdit={editProperty}
                embedded={false}
            />
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.group(groupData.group_type_index, groupData.group_key, true, 'properties')}
                >
                    View properties
                </LemonButton>
            </div>
        </div>
    )
}
