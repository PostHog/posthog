import { Button, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import React, { useEffect, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export function PersonDisplayNameProperties(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])

    useEffect(() => setValue(currentTeam?.person_display_name_properties || []), [currentTeam])

    if (!currentTeam) {
        return <Skeleton paragraph={{ rows: 0 }} active />
    }

    return (
        <>
            <p>
                You can choose a list of properties for Persons that will be used if available. Drag the property to
                re-order the priority (left-to-right).
            </p>
            <div>
                <PersonPropertySelect
                    onChange={(properties) => setValue(properties)}
                    selectedProperties={value || []}
                    addText="Add"
                    sortable
                />
                <Button
                    type="primary"
                    onClick={() =>
                        updateCurrentTeam({
                            person_display_name_properties: value.map((s) => s.trim()).filter((a) => a) || [],
                        })
                    }
                >
                    Save
                </Button>
            </div>
        </>
    )
}
