import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { insertPromptReferenceLogic } from './insertPromptReferenceLogic'
import { PromptReferencePicker } from './PromptReferencePicker'

export function InsertPromptReferenceButton({
    currentPromptName,
    onInsert,
}: {
    currentPromptName: string
    onInsert: (tag: string) => void
}): JSX.Element {
    const { promptOptionsLoading } = useValues(insertPromptReferenceLogic)
    const { loadPromptOptions } = useActions(insertPromptReferenceLogic)
    const [isOpen, setIsOpen] = useState(false)

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconPlusSmall />}
                loading={!isOpen && promptOptionsLoading}
                tooltip="Insert a reference to another prompt. Its content replaces the tag when the prompt is fetched."
                data-attr="llma-prompt-insert-reference-button"
                onClick={(e) => {
                    e.preventDefault()
                    if (promptOptionsLoading) {
                        return
                    }
                    setIsOpen(true)
                    loadPromptOptions('')
                }}
            >
                Insert reference
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Insert prompt reference"
                description="Reference a label to pick up its future moves, or pin a version to freeze the content."
                width={480}
            >
                <PromptReferencePicker
                    currentPromptName={currentPromptName}
                    onSelect={(tag) => {
                        onInsert(tag)
                        setIsOpen(false)
                    }}
                />
            </LemonModal>
        </>
    )
}
