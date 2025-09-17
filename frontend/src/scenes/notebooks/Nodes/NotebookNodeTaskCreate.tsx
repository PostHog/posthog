import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'

import { tasksLogic } from 'products/tasks/frontend/tasksLogic'
import { OriginProduct, TaskUpsertProps } from 'products/tasks/frontend/types'

import { notebookNodeLogic } from './notebookNodeLogic'

type NotebookNodeTaskCreateAttributes = {
    title: string
    description?: string
    severity?: string
}

function Component({ attributes }: NotebookNodeProps<NotebookNodeTaskCreateAttributes>): JSX.Element | null {
    const { createTask } = useActions(tasksLogic)
    const { expanded } = useValues(notebookNodeLogic)
    const [title, setTitle] = useState<string>(attributes.title || '')
    const [description, setDescription] = useState<string>(attributes.description || '')

    const onCreate = (): void => {
        const payload: TaskUpsertProps = {
            title: title,
            description: description,
            origin_product: OriginProduct.SESSION_SUMMARIES,
        }
        createTask(payload)
    }

    const parsedSeverity =
        attributes.severity ||
        attributes.description
            ?.split('\n')
            .map((l) => l.trim())
            .find((l) => l.toLowerCase().startsWith('severity:'))
            ?.split(':')[1]
            ?.trim() ||
        ''

    return expanded ? (
        <div className="p-2 flex flex-col gap-2">
            <LemonTextArea value={title} onChange={setTitle} placeholder="Task title" minRows={1} maxRows={3} />
            <LemonTextArea
                value={description}
                onChange={setDescription}
                placeholder="Task description"
                minRows={3}
                maxRows={10}
            />
            <div className="flex justify-end">
                <LemonButton icon={<IconPlus />} size="small" onClick={onCreate} type="primary">
                    Create as task
                </LemonButton>
            </div>
        </div>
    ) : (
        <div className="p-2 flex items-center gap-2 text-muted">
            {parsedSeverity ? (
                <LemonTag size="small" type={parsedSeverity.toLowerCase() === 'critical' ? 'danger' : 'warning'}>
                    {parsedSeverity}
                </LemonTag>
            ) : null}
            {!parsedSeverity ? <span className="truncate">Click to open and review</span> : null}
        </div>
    )
}

export const NotebookNodeTaskCreate = createPostHogWidgetNode<NotebookNodeTaskCreateAttributes>({
    nodeType: NotebookNodeType.TaskCreate,
    titlePlaceholder: 'Suggested task',
    startExpanded: false,
    Component,
    resizeable: false,
    heightEstimate: '10rem',
    minHeight: '8rem',
    attributes: {
        title: { default: '' },
        description: { default: '' },
        severity: { default: '' },
    },
})
