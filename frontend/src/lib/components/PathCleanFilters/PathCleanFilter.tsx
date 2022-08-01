import React, { useState } from 'react'
import { LemonInput } from '../LemonInput/LemonInput'
import { LemonButton } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'

interface PathRegexPopupProps {
    onComplete: (newItem: Record<string, any>) => void
    onClose: () => void
    item: Record<string, any>
}

export function PathRegexPopup({ item, onComplete, onClose }: PathRegexPopupProps): JSX.Element {
    const [alias, setAlias] = useState(item['alias'])
    const [regex, setRegex] = useState(item['regex'])

    return (
        <div className="px-2">
            <b>New Wildcard</b>
            <LemonDivider />
            <div className="space-y-2">
                <div>
                    <span>Alias</span>
                    <LemonInput defaultValue={alias} onChange={(e) => setAlias(e)} onPressEnter={() => false} />
                </div>
                <div>
                    <span>Regex</span>
                    <LemonInput defaultValue={regex} onChange={(e) => setRegex(e)} onPressEnter={() => false} />
                    <div className="text-muted" style={{ marginBottom: 12 }}>
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
