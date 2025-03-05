import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { isValidRegexp } from 'lib/utils/regexp'
import { useState } from 'react'
import { AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'
import { AiRegexHelper } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'

import { PathCleaningFilter } from '~/types'

export interface PathRegexModalProps {
    isOpen: boolean
    onSave: (filter: PathCleaningFilter) => void
    onClose: () => void
    filter?: PathCleaningFilter
}

export function PathRegexModal({ filter, isOpen, onSave, onClose }: PathRegexModalProps): JSX.Element {
    const [alias, setAlias] = useState(filter?.alias ?? '')
    const [regex, setRegex] = useState(filter?.regex ?? '')

    const isNew = !filter
    const disabledReason = !alias
        ? 'Alias is required'
        : !regex
        ? 'Regex is required'
        : !isValidRegexp(regex)
        ? 'Malformed regex'
        : null

    return (
        <LemonModal isOpen={isOpen} onClose={onClose}>
            <LemonModal.Header>
                {isNew ? <b>Add Path Cleaning Rule</b> : <b>Edit Path Cleaning Rule</b>}
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="px-2 py-1" data-attr="path-regex-modal-content">
                    <div className="space-y-2">
                        <div>
                            <span>Alias</span>
                            <LemonInput
                                value={alias}
                                onChange={(alias) => setAlias(alias)}
                                onPressEnter={() => false}
                            />
                            <div className="text-muted">
                                We suggest you use <code>&lt;id&gt;</code> or <code>&lt;slug&gt;</code> to indicate a
                                dynamic part of the path.
                            </div>
                        </div>
                        <div>
                            <span>Regex</span>
                            <LemonInput
                                value={regex}
                                onChange={(regex) => setRegex(regex)}
                                onPressEnter={() => false}
                            />
                            <p className="text-secondary">
                                <span>
                                    Example:{' '}
                                    <span className="font-mono text-accent-primary text-xs">
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

                    <div className="flex space-between mt-3">
                        <AiRegexHelper onApply={setRegex} />
                        <AiRegexHelperButton />

                        <div className="flex flex-1 justify-end gap-2">
                            <LemonButton type="secondary" onClick={onClose}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => onSave({ alias, regex })}
                                disabledReason={disabledReason}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
