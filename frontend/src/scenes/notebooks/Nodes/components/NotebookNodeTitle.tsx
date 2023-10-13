import { KeyboardEvent } from 'react'
import { useActions, useValues } from 'kea'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { useEffect, useState } from 'react'
import { LemonInput, Tooltip } from '@posthog/lemon-ui'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

export function NotebookNodeTitle(): JSX.Element {
    const { isEditable } = useValues(notebookLogic)
    const { nodeAttributes, title, titlePlaceholder } = useValues(notebookNodeLogic)
    const { updateAttributes } = useActions(notebookNodeLogic)
    const [editing, setEditing] = useState(false)
    const [newValue, setNewValue] = useState('')

    useEffect(() => {
        setNewValue(nodeAttributes.title ?? '')
    }, [editing])

    const commitEdit = (): void => {
        updateAttributes({
            title: newValue ?? undefined,
        })

        setEditing(false)
    }

    const onKeyUp = (e: KeyboardEvent<HTMLInputElement>): void => {
        // Esc cancels, enter commits
        if (e.key === 'Escape') {
            setEditing(false)
        } else if (e.key === 'Enter') {
            commitEdit()
        }
    }

    return !isEditable ? (
        <span title={title} className="NotebookNodeTitle">
            {title}
        </span>
    ) : !editing ? (
        <Tooltip title={'Double click to edit title'}>
            <span
                title={title}
                className="NotebookNodeTitle NotebookNodeTitle--editable"
                onDoubleClick={() => setEditing(true)}
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
