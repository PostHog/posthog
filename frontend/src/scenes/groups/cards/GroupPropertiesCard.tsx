import { useActions } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useMemo } from 'react'
import { urls } from 'scenes/urls'

import { Group, PropertyDefinitionType } from '~/types'

import { groupLogic } from '../groupLogic'
import { GroupCard } from './GroupCard'

export function GroupPropertiesCard({ groupData }: { groupData: Group }): JSX.Element {
    const { editProperty } = useActions(groupLogic)
    const propertySummary = useMemo(() => {
        return Object.fromEntries(
            Object.entries(groupData.group_properties || {})
                .filter(([_, value]) => typeof value !== 'object' || value === null)
                .slice(0, 6)
        )
    }, [groupData.group_properties])

    return (
        <div className="flex flex-col gap-2">
            <GroupCard>
                <PropertiesTable
                    type={PropertyDefinitionType.Group}
                    properties={propertySummary || {}}
                    embedded={true}
                    onEdit={editProperty}
                />
            </GroupCard>
            <div className="flex justify-start">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.group(groupData.group_type_index, groupData.group_key)}
                >
                    View properties
                </LemonButton>
            </div>
        </div>
    )
}
