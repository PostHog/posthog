import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import { isValidRegexp } from 'lib/utils/regexp'
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

    const disabledReason = !alias
        ? 'Alias is required'
        : !regex
        ? 'Regex is required'
        : !isValidRegexp(regex)
        ? 'Malformed regex'
        : null

    return (
        <div className="px-2 py-1">
            {isNew ? <b>Add Path Cleaning Rule</b> : <b>Edit Path Cleaning Rule</b>}
            <LemonDivider />
            <div className="space-y-2">
                <div>
                    <span>Alias</span>
                    <LemonInput defaultValue={alias} onChange={(alias) => setAlias(alias)} onPressEnter={() => false} />
                    <div className="text-muted">
                        We suggest you use <code>&lt;id&gt;</code> or <code>&lt;slug&gt;</code> to indicate a dynamic
                        part of the path.
                    </div>
                </div>
                <div>
                    <span>Regex</span>
                    <LemonInput defaultValue={regex} onChange={(regex) => setRegex(regex)} onPressEnter={() => false} />
                    <p className="text-secondary">
                        <span>
                            Example:{' '}
                            <span title={filter.regex} className="font-mono text-accent-primary text-xs">
                                /merchant/\d+/dashboard$
                            </span>{' '}
                            (no need to escape slashes)
                        </span>{' '}
                        <br />
                        <span>
                            We use the{' '}
                            <Link to="https://github.com/google/re2/wiki/Syntax" target="_blank">
                                re2
                            </Link>{' '}
                            syntax.
                        </span>
                    </p>
                </div>
            </div>

            <div className="flex justify-end gap-2 mt-3">
                <LemonButton type="secondary" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" onClick={() => onSave({ alias, regex })} disabledReason={disabledReason}>
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
