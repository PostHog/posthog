import { useActions } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'

import { tasksLogic } from 'products/tasks/frontend/tasksLogic'
import { OriginProduct, TaskStatus, TaskUpsertProps } from 'products/tasks/frontend/types'

type NotebookNodeTaskCreateAttributes = {
    title: string
    description?: string
}

function Component({ attributes }: NotebookNodeProps<NotebookNodeTaskCreateAttributes>): JSX.Element | null {
    const { createTask } = useActions(tasksLogic)
    const [title, setTitle] = useState<string>(attributes.title || '')
    const [description, setDescription] = useState<string>(attributes.description || '')

    const onCreate = (): void => {
        const payload: TaskUpsertProps = {
            title: title || attributes.title,
            description: description || attributes.description || '',
            status: TaskStatus.BACKLOG,
            origin_product: OriginProduct.USER_CREATED,
        }
        createTask(payload)
    }

    return (
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
    )
}

export const NotebookNodeTaskCreate = createPostHogWidgetNode<NotebookNodeTaskCreateAttributes>({
    nodeType: NotebookNodeType.TaskCreate,
    titlePlaceholder: 'Create task',
    Component,
    heightEstimate: '10rem',
    minHeight: '8rem',
    attributes: {
        title: { default: '' },
        description: { default: '' },
    },
})
