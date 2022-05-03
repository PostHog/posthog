import { Button, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import React, { useEffect, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export function PersonDisplayNameProperties(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])

    useEffect(
        () => setValue(currentTeam?.person_display_name_properties || PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES),
        [currentTeam]
    )

    if (!currentTeam) {
        return <Skeleton paragraph={{ rows: 0 }} active />
    }

    return (
        <>
            <p>
                Choose which properties of an identified Person will be used for their <b>Display Name</b>. The first
                property to be found on the Person will be used. Drag the items to re-order the priority.
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
