import { useActions, useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useMemo } from 'react'

import { Group, PropertyDefinitionType } from '~/types'

import { groupLogic } from './groupLogic'

function GroupPropertiesModal({ groupData }: { groupData: Group }): JSX.Element {
    const { isPropertiesModalOpen } = useValues(groupLogic)
    const { editProperty, deleteProperty, setIsPropertiesModalOpen } = useActions(groupLogic)
    return (
        <LemonModal
            isOpen={isPropertiesModalOpen}
            onClose={() => setIsPropertiesModalOpen(false)}
            footer={
                <LemonButton type="secondary" onClick={() => setIsPropertiesModalOpen(false)}>
                    Close
                </LemonButton>
            }
        >
            <PropertiesTable
                type={PropertyDefinitionType.Group}
                properties={groupData.group_properties || {}}
                embedded={false}
                onEdit={editProperty}
                onDelete={deleteProperty}
                searchable
            />
        </LemonModal>
    )
}

export function GroupProperties({ groupData }: { groupData: Group }): JSX.Element {
    const { editProperty, setIsPropertiesModalOpen } = useActions(groupLogic)

    const propertySummary = useMemo(() => {
        return Object.fromEntries(
            Object.entries(groupData.group_properties || {})
                .filter(([_, value]) => typeof value !== 'object' || value === null)
                .slice(0, 6)
        )
    }, [groupData.group_properties])

    return (
        <>
            <PropertiesTable
                type={PropertyDefinitionType.Group}
                properties={propertySummary || {}}
                embedded={false}
                onEdit={editProperty}
                tableProps={{
                    footer: (
                        <LemonButton onClick={() => setIsPropertiesModalOpen(true)}>View all properties</LemonButton>
                    ),
                }}
            />
            <GroupPropertiesModal groupData={groupData} />
        </>
    )
}
