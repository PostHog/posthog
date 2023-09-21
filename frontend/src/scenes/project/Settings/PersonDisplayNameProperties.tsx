import { LemonButton, LemonSnack } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { useEffect, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export function PersonDisplayNameProperties(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])
    const [suggestions, setSuggestions] = useState([] as string[])

    useEffect(() => {
        setValue(currentTeam?.person_display_name_properties || [])
        setSuggestions(PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES)
    }, [currentTeam])

    if (!currentTeam) {
        return <LemonSkeleton className="w-1/2" />
    }

    const activeSuggestions = suggestions.filter((s) => !value.includes(s))

    return (
        <>
            <p>
                Choose which properties of an identified Person will be used for their <b>Display Name</b>. The first
                property to be found on the Person will be used. Drag the items to re-order the priority.
            </p>
            <div className="space-y-4">
                <PersonPropertySelect
                    onChange={(properties) => setValue(properties)}
                    selectedProperties={value || []}
                    addText="Add"
                    sortable
                />
                <div>
                    <h4>Suggestions</h4>
                    <div className="space-x-1">
                        {activeSuggestions.map((suggestion) => (
                            <LemonSnack key={suggestion} onClick={() => setValue([...value, suggestion])}>
                                {suggestion}
                            </LemonSnack>
                        ))}
                    </div>
                </div>
                <LemonButton
                    type="primary"
                    onClick={() =>
                        updateCurrentTeam({
                            person_display_name_properties: value.map((s) => s.trim()).filter((a) => a) || [],
                        })
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
