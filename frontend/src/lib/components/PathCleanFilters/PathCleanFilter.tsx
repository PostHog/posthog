import { useState } from 'react'

import { LemonInput, LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { PathCleaningFilter } from '~/types'

interface PathRegexPopupProps {
    onComplete: (newItem: PathCleaningFilter) => void
    onClose: () => void
    item: PathCleaningFilter
}

export function PathRegexPopup({ item, onComplete, onClose }: PathRegexPopupProps): JSX.Element {
    const [alias, setAlias] = useState(item.alias)
    const [regex, setRegex] = useState(item.regex)

    return (
        <div className="px-2">
            <b>New Wildcard</b>
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
                <LemonButton type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" onClick={() => onComplete({ alias, regex })}>
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
