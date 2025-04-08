import { IconInfo } from '@posthog/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useState } from 'react'

import { RecordingUniversalFilters } from '~/types'

export function PeopleFilter({
    setFilters,
}: {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const [value, setValue] = useState('')
    return (
        <>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    value={value}
                    placeholder="Search for persons"
                    data-attr="persons-search"
                    onChange={setValue}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            setFilters({})
                        }
                    }}
                />
                <Tooltip title="Search for persons">
                    <IconInfo className="text-2xl text-secondary shrink-0" />
                </Tooltip>
            </div>
        </>
    )
}
