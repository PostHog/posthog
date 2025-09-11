import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { tasksLogic } from '../tasksLogic'
import { TaskCard } from './TaskCard'
import { TaskCreateModal } from './TaskCreateModal'
import { TaskModal } from './TaskModal'

export function BacklogView(): JSX.Element {
    const { backlogTasks, selectedTask, isCreateModalOpen } = useValues(tasksLogic)
    const { scopeTask, openTaskModal, closeTaskModal, openCreateModal, closeCreateModal } = useActions(tasksLogic)

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-xl font-semibold">Backlog</h2>
                <div className="flex items-center gap-3">
                    <span className="text-sm text-muted">{backlogTasks.length} tasks</span>
                    <LemonButton type="primary" onClick={openCreateModal}>
                        Create Task
                    </LemonButton>
                </div>
            </div>

            <div className="space-y-2">
                {backlogTasks.map((task) => (
                    <TaskCard key={task.id} task={task} onScope={scopeTask} onClick={openTaskModal} />
                ))}
            </div>

            {backlogTasks.length === 0 && <div className="text-center py-8 text-muted">No tasks in backlog</div>}

            {selectedTask && <TaskModal task={selectedTask} onClose={closeTaskModal} />}
            <TaskCreateModal isOpen={isCreateModalOpen} onClose={closeCreateModal} />
        </div>
    )
}
