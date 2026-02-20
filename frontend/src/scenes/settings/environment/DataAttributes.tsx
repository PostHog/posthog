import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { teamLogic } from 'scenes/teamLogic'

export function DataAttributes(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])

    useEffect(() => setValue(currentTeam?.data_attributes || []), [currentTeam])

    if (!currentTeam) {
        return <LemonSkeleton />
    }

    return (
        <>
            <div className="deprecated-space-y-4 max-w-160">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    onChange={(values: string[]) => setValue(values || [])}
                    value={value}
                    data-attr="data-attribute-select"
                    placeholder="data-attr, ..."
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading}
                />
                <LemonButton
                    type="primary"
                    onClick={() =>
                        updateCurrentTeam({ data_attributes: value.map((s) => s.trim()).filter((a) => a) || [] })
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
