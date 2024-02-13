import { LemonInput, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { KeyboardEvent } from 'react'
import { useEffect, useState } from 'react'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { notebookNodeLogic } from '../notebookNodeLogic'

export function NotebookNodeTitle(): JSX.Element {
    const { isEditable } = useValues(notebookLogic)
    const { nodeAttributes, title, titlePlaceholder, isEditingTitle } = useValues(notebookNodeLogic)
    const { updateAttributes, toggleEditingTitle } = useActions(notebookNodeLogic)
    const [newValue, setNewValue] = useState('')

    useEffect(() => {
        setNewValue(nodeAttributes.title ?? '')
    }, [isEditingTitle])

    const commitEdit = (): void => {
        updateAttributes({
            title: newValue ?? undefined,
        })

        if (title != newValue) {
            posthog.capture('notebook node title updated')
        }

        toggleEditingTitle(false)
    }

    const onKeyUp = (e: KeyboardEvent<HTMLInputElement>): void => {
        // Esc cancels, enter commits
        if (e.key === 'Escape') {
            toggleEditingTitle(false)
        } else if (e.key === 'Enter') {
            commitEdit()
        }
    }

    return !isEditable ? (
        <span title={title} className="NotebookNodeTitle">
            {title}
        </span>
    ) : !isEditingTitle ? (
        <Tooltip title="Double click to edit title">
            <span
                title={title}
                className="NotebookNodeTitle NotebookNodeTitle--editable"
                onDoubleClick={() => {
                    toggleEditingTitle(true)
                    posthog.capture('notebook editing node title')
                }}
            >
                {title}
            </span>
        </Tooltip>
    ) : (
        <LemonInput
            autoFocus
            placeholder={titlePlaceholder}
            size="small"
            fullWidth
            value={newValue}
            onChange={(e) => setNewValue(e)}
            onBlur={commitEdit}
            onKeyUp={onKeyUp}
            onFocus={(e) => e.target.select()}
        />
    )
}
