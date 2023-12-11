import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

interface PathRegexPopoverProps {
    filter?: PathCleaningFilter
    onSave: (filter: PathCleaningFilter) => void
    onCancel: () => void
    /** Wether we're editing an existing filter or adding a new one */
    isNew?: boolean
}

export function PathRegexPopover({ filter = {}, onSave, onCancel, isNew = false }: PathRegexPopoverProps): JSX.Element {
    const [alias, setAlias] = useState(filter.alias)
    const [regex, setRegex] = useState(filter.regex)

    return (
        <div className="px-2 py-1">
            {isNew ? <b>Add Path Cleaning Rule</b> : <b>Edit Path Cleaning Rule</b>}
            <LemonDivider />
            <div className="space-y-2">
                <div>
                    <span>Alias</span>
                    <LemonInput defaultValue={alias} onChange={(alias) => setAlias(alias)} onPressEnter={() => false} />
                </div>
                <div>
                    <span>Regex</span>
                    <LemonInput defaultValue={regex} onChange={(regex) => setRegex(regex)} onPressEnter={() => false} />
                    <div className="text-muted mb-3">
                        For example: <code>\/merchant\/\d+\/dashboard$</code>
                    </div>
                </div>
            </div>

            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" onClick={() => onSave({ alias, regex })}>
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
