import React from 'react'
import { Button, Card } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/sessionsFiltersLogic'

interface Props {
    i?: boolean
}

export function SessionsEditFiltersPanel({}: Props): JSX.Element {
    const { displayedFilters } = useValues(sessionsFiltersLogic)
    const { openFilterSelect } = useActions(sessionsFiltersLogic)

    return (
        <Card>
            <pre>{JSON.stringify(displayedFilters, null, 2)}</pre>

            <Button onClick={() => openFilterSelect('new')}>+</Button>
            <Button>collapse</Button>
        </Card>
    )
}
