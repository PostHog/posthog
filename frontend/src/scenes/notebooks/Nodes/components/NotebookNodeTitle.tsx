import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { KeyboardEvent, useEffect, useMemo, useState } from 'react'

import { LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { isHogQLQuery } from '~/queries/utils'

import { NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'

const collectNodeIndices = (
    content: Record<string, any> | null | undefined,
    predicate: (node: Record<string, any>) => boolean
): Map<string, number> => {
    if (!content || typeof content !== 'object') {
        return new Map()
    }

    const nodeIndices = new Map<string, number>()
    let currentIndex = 0

    const walk = (node: Record<string, any> | null | undefined): void => {
        if (!node || typeof node !== 'object') {
            return
        }

        if (predicate(node)) {
            const nodeId = node.attrs?.nodeId
            if (nodeId) {
                currentIndex += 1
                nodeIndices.set(nodeId, currentIndex)
            }
        }

        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodeIndices
}

export function NotebookNodeTitle(): JSX.Element {
    const { isEditable, content } = useValues(notebookLogic)
    const { nodeAttributes, title, titlePlaceholder, isEditingTitle, nodeType } = useValues(notebookNodeLogic)
    const { updateAttributes, toggleEditingTitle } = useActions(notebookNodeLogic)
    const [newValue, setNewValue] = useState('')

    const pythonNodeIndices = useMemo(
        () => collectNodeIndices(content, (node) => node.type === NotebookNodeType.Python),
        [content]
    )
    const sqlNodeIndices = useMemo(
        () =>
            collectNodeIndices(
                content,
                (node) =>
                    node.type === NotebookNodeType.Query &&
                    (isHogQLQuery(node.attrs?.query) ||
                        (node.attrs?.query.source && isHogQLQuery(node.attrs.query.source)))
            ),
        [content]
    )

    const isPythonNode = nodeType === NotebookNodeType.Python
    const isSqlNode =
        nodeType === NotebookNodeType.Query &&
        (isHogQLQuery(nodeAttributes.query) ||
            (nodeAttributes.query.source && isHogQLQuery(nodeAttributes.query.source)))

    const nodeIndex = isPythonNode
        ? pythonNodeIndices.get(nodeAttributes.nodeId)
        : isSqlNode
          ? sqlNodeIndices.get(nodeAttributes.nodeId)
          : undefined
    const cellLabel = nodeIndex ? `${isPythonNode ? 'Python' : 'SQL'} ${nodeIndex}` : null
    const customTitle = nodeAttributes.title
    const cellTitle = cellLabel ? (customTitle ? `${cellLabel} • ${customTitle}` : cellLabel) : title

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

    const cellTitleDisplay = cellLabel ? (
        <span title={cellTitle} className="NotebookNodeTitle flex items-center gap-2 truncate">
            <span className="font-semibold">{cellLabel}</span>
            {customTitle ? <span className="text-muted truncate">{customTitle}</span> : null}
        </span>
    ) : (
        <span title={title} className="NotebookNodeTitle">
            {title}
        </span>
    )

    return !isEditable ? (
        nodeType === NotebookNodeType.TaskCreate ? (
            suggestedTaskTitle
        ) : (
            cellTitleDisplay
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
                    title={cellTitle}
                    className="NotebookNodeTitle NotebookNodeTitle--editable"
                    onDoubleClick={() => {
                        toggleEditingTitle(true)
                        posthog.capture('notebook editing node title')
                    }}
                >
                    {cellLabel ? (
                        <span className="flex items-center gap-2 truncate">
                            <span className="font-semibold">{cellLabel}</span>
                            {customTitle ? <span className="text-muted truncate">{customTitle}</span> : null}
                        </span>
                    ) : (
                        title
                    )}
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
