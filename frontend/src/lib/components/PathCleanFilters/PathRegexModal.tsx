import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'
import { AiRegexHelper } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'

import { PathCleaningFilter } from '~/types'

import { isValidPathCleaningRegex } from './pathCleaningUtils'

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
          : !isValidPathCleaningRegex(regex)
            ? 'Malformed regex'
            : null

    // Reset state when reopening the modal with a different filter (or none)
    useEffect(() => {
        if (isOpen) {
            setAlias(filter?.alias ?? '')
            setRegex(filter?.regex ?? '')
        }
    }, [isOpen, filter])

    return (
        <LemonModal isOpen={isOpen} onClose={onClose}>
            <LemonModal.Header>
                {isNew ? <b>Add Path Cleaning Rule</b> : <b>Edit Path Cleaning Rule</b>}
            </LemonModal.Header>

            <LemonModal.Content>
                <div className="px-2 py-1" data-attr="path-regex-modal-content">
                    <div className="deprecated-space-y-2">
                        <div>
                            <span>Regex</span>
                            <LemonInput
                                value={regex}
                                onChange={(regex) => setRegex(regex)}
                                onPressEnter={() => false}
                            />
                            <p className="text-muted">
                                <span>
                                    Example:{' '}
                                    <span className="font-mono text-accent text-xs">/merchant/\d+/dashboard$</span> (no
                                    need to escape slashes)
                                </span>
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
                        <div>
                            <span>Alias</span>
                            <LemonInput
                                value={alias}
                                onChange={(alias) => setAlias(alias)}
                                onPressEnter={() => false}
                            />
                            <p className="text-muted">
                                <span>How the path will appear after path cleaning</span>
                                <br />
                                <span>
                                    Example:{' '}
                                    <span className="font-mono text-accent text-xs">{'/merchant/<id>/dashboard'}</span>
                                </span>
                                <br />
                                <span>
                                    To keep part of the original path, reference a capture group from the regex with{' '}
                                    <span className="font-mono text-accent text-xs">{'\\1'}</span>,{' '}
                                    <span className="font-mono text-accent text-xs">{'\\2'}</span>, and so on. For
                                    example, regex{' '}
                                    <span className="font-mono text-accent text-xs">{'/user/(\\d+)/profile'}</span> with
                                    alias <span className="font-mono text-accent text-xs">{'/user/\\1'}</span> keeps the
                                    id. Capture groups slow queries down, so use them when one rule can replace several
                                    near-identical ones.
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
                                onClick={() => {
                                    onSave({
                                        alias: alias.trim(),
                                        regex: regex.trim(),
                                        order: filter?.order,
                                    })
                                }}
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
