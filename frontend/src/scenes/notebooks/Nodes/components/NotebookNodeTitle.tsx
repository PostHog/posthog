import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { KeyboardEvent } from 'react'
import { useEffect, useState } from 'react'

import { LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'

export function NotebookNodeTitle(): JSX.Element {
    const { isEditable } = useValues(notebookLogic)
    const { nodeAttributes, title, titlePlaceholder, isEditingTitle, nodeType } = useValues(notebookNodeLogic)
    const { updateAttributes, toggleEditingTitle } = useActions(notebookNodeLogic)
    const [newValue, setNewValue] = useState('')

    useEffect(() => {
        setNewValue(nodeAttributes.title ?? '')
    }, [isEditingTitle]) // oxlint-disable-line react-hooks/exhaustive-deps

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

    const suggestedTaskTitle = (
        <span className="NotebookNodeTitle flex items-center gap-2" title={title}>
            <LemonTag type="warning" size="small">
                Suggested task
            </LemonTag>
            <span className="truncate">{title}</span>
        </span>
    )

    return !isEditable ? (
        nodeType === NotebookNodeType.TaskCreate ? (
            suggestedTaskTitle
        ) : (
            <span title={title} className="NotebookNodeTitle">
                {title}
            </span>
        )
    ) : !isEditingTitle ? (
        <Tooltip title="Double click to edit title">
            {nodeType === NotebookNodeType.TaskCreate ? (
                <span
                    title={title}
                    className="NotebookNodeTitle NotebookNodeTitle--editable"
                    onDoubleClick={() => {
                        toggleEditingTitle(true)
                        posthog.capture('notebook editing node title')
                    }}
                >
                    {suggestedTaskTitle}
                </span>
            ) : (
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
            )}
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
