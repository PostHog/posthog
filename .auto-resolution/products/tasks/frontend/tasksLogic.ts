import { UniqueIdentifier } from '@dnd-kit/core'
import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { demoTasks } from './demoData'
import type { tasksLogicType } from './tasksLogicType'
import { Task, TaskStatus, TaskUpsertProps } from './types'

export const tasksLogic = kea<tasksLogicType>([
    path(['products', 'tasks', 'frontend', 'tasksLogic']),
    actions({
        setActiveTab: (tab: 'backlog' | 'kanban' | 'settings') => ({ tab }),
        moveTask: (taskId: string, newStatus: TaskStatus, newPosition?: number) => ({
            taskId,
            newStatus,
            newPosition,
        }),
        createTask: (task: TaskUpsertProps) => ({ task }),
        updateTask: (id: Task['id'], data: Partial<TaskUpsertProps>) => ({ id, data }),
        scopeTask: (taskId: string) => ({ taskId }),
        reorderTasks: (sourceIndex: number, destinationIndex: number, status: TaskStatus) => ({
            sourceIndex,
            destinationIndex,
            status,
        }),
        openTaskModal: (taskId: Task['id']) => ({ taskId }),
        closeTaskModal: true,
        openCreateModal: true,
        closeCreateModal: true,
        startPolling: true,
        stopPolling: true,
        pollForUpdates: true,
        startReordering: true,
        endReordering: true,
    }),
    loaders(({ values, actions }) => ({
        tasks: [
            [] as Task[],
            {
                loadTasks: async () => {
                    try {
                        const response = await api.tasks.list()
                        return response.results
                    } catch (error) {
                        console.error('Failed to load tasks, using demo data:', error)
                        return demoTasks
                    }
                },
                createTask: async ({ task }) => {
                    try {
                        const response = await api.tasks.create(task)
                        return [...values.tasks, response]
                    } catch (error) {
                        lemonToast.error('Failed to create task. Please try again.')
                        console.error('Failed to create task:', error)
                        throw error
                    }
                },
                updateTask: async ({ id, data }) => {
                    try {
                        const response = await api.tasks.update(id, data)
                        return [...values.tasks].map((task) => (task.id === id ? { ...task, ...response } : task))
                    } catch (error) {
                        lemonToast.error('Failed to update task. Please try again.')
                        console.error('Failed to update task:', error)
                        throw error
                    }
                },
                moveTask: async ({ taskId, newStatus, newPosition }) => {
                    actions.startReordering()
                    // Optimistic update + schedule bulk reorder to persist
                    const currentTasks = [...values.tasks]
                    const moved = currentTasks.find((t) => t.id === taskId)
                    if (!moved) {
                        actions.endReordering()
                        return currentTasks
                    }

                    const sourceStatus = moved.status
                    const sourceList = currentTasks
                        .filter((t) => t.status === sourceStatus && t.id !== taskId)
                        .sort((a, b) => a.position - b.position)
                    const targetList = currentTasks
                        .filter((t) => t.status === newStatus && t.id !== taskId)
                        .sort((a, b) => a.position - b.position)

                    const insertIndex = Math.min(Math.max(newPosition ?? targetList.length, 0), targetList.length)

                    const updatedTargetList = [
                        ...targetList.slice(0, insertIndex),
                        { ...moved, status: newStatus },
                        ...targetList.slice(insertIndex),
                    ]

                    // Build new tasks snapshot with reindexed positions
                    const sourceIds = sourceList.map((t) => t.id)
                    const targetIds = updatedTargetList.map((t) => t.id)
                    const updatedTasks = currentTasks.map((t) => {
                        if (t.id === taskId) {
                            return {
                                ...t,
                                status: newStatus,
                                position: targetIds.indexOf(t.id),
                                updated_at: new Date().toISOString(),
                            }
                        }
                        if (t.status === sourceStatus && sourceIds.includes(t.id)) {
                            return { ...t, position: sourceIds.indexOf(t.id) }
                        }
                        if (t.status === newStatus && targetIds.includes(t.id)) {
                            return { ...t, position: targetIds.indexOf(t.id) }
                        }
                        return t
                    })

                    // Persist via bulkReorder for both affected columns
                    const columns: Record<string, string[]> = {}
                    columns[sourceStatus] = sourceIds
                    columns[newStatus] = targetIds
                    api.tasks
                        .bulkReorder(columns)
                        .then(() => {})
                        .catch(() => {
                            actions.loadTasks()
                        })
                        .finally(() => {
                            actions.endReordering()
                        })

                    return updatedTasks
                },
                scopeTask: async ({ taskId }) => {
                    const todoTasks = values.tasks.filter((task: Task) => task.status === TaskStatus.TODO)
                    const nextPosition = todoTasks.length

                    // Optimistic update
                    const currentTasks = values.tasks.map((task) =>
                        task.id === taskId && task.status === TaskStatus.BACKLOG
                            ? {
                                  ...task,
                                  status: TaskStatus.TODO,
                                  position: nextPosition,
                                  updated_at: new Date().toISOString(),
                              }
                            : task
                    )

                    // Update in background
                    api.tasks
                        .update(taskId, {
                            status: TaskStatus.TODO,
                            position: nextPosition,
                        })
                        .catch(() => {
                            actions.loadTasks()
                        })

                    return currentTasks
                },
                reorderTasks: async ({ sourceIndex, destinationIndex, status }) => {
                    const statusTasks = values.tasks
                        .filter((task: Task) => task.status === status)
                        .sort((a, b) => a.position - b.position)

                    const movedTask = statusTasks[sourceIndex]
                    if (!movedTask) {
                        return values.tasks
                    }

                    // Optimistic update - reorder locally first
                    const reorderedStatusTasks = [...statusTasks]
                    reorderedStatusTasks.splice(sourceIndex, 1)
                    reorderedStatusTasks.splice(destinationIndex, 0, movedTask)

                    // Update positions for all affected items
                    const currentTasks = values.tasks.map((task) => {
                        if (task.status === status) {
                            const newIndex = reorderedStatusTasks.findIndex((st) => st.id === task.id)
                            return { ...task, position: newIndex }
                        }
                        return task
                    })

                    // Update positions in background
                    const positionUpdates = reorderedStatusTasks.map((task, index) => {
                        if (task.position !== index) {
                            return api.tasks.update(task.id, { position: index })
                        }
                        return Promise.resolve()
                    })

                    Promise.all(positionUpdates).catch(() => {
                        actions.loadTasks()
                    })

                    return currentTasks
                },
                pollForUpdates: async () => {
                    // Avoid clobbering optimistic state while reordering
                    if (values.isReordering) {
                        return values.tasks
                    }
                    try {
                        const response = await api.tasks.list()
                        return response.results
                    } catch (error) {
                        console.error('Polling failed:', error)
                        return values.tasks
                    }
                },
            },
        ],
    })),
    reducers({
        activeTab: [
            'backlog' as 'backlog' | 'kanban' | 'settings',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        selectedTaskId: [
            null as string | null,
            {
                openTaskModal: (_, { taskId }) => taskId,
                closeTaskModal: () => null,
            },
        ],
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
        pollingInterval: [
            null as number | null,
            {
                startPolling: () => null, // Set in listener
                stopPolling: () => null,
            },
        ],
        isReordering: [
            false,
            {
                startReordering: () => true,
                endReordering: () => false,
            },
        ],
    }),
    selectors({
        backlogTasks: [
            (s) => [s.tasks],
            (tasks): Task[] =>
                tasks.filter((task) => task.status === TaskStatus.BACKLOG).sort((a, b) => a.position - b.position),
        ],
        kanbanColumns: [
            (s) => [s.tasks],
            (tasks): Record<UniqueIdentifier, Task[]> => {
                const buckets = tasks.reduce(
                    (acc, task) => {
                        acc[task.status].push(task)
                        return acc
                    },
                    {
                        [TaskStatus.BACKLOG]: [],
                        [TaskStatus.TODO]: [],
                        [TaskStatus.IN_PROGRESS]: [],
                        [TaskStatus.TESTING]: [],
                        [TaskStatus.DONE]: [],
                    } as Record<TaskStatus, Task[]>
                )
                // Sort each column by position
                ;(Object.keys(buckets) as Array<keyof typeof buckets>).forEach((k) => {
                    buckets[k] = buckets[k].slice().sort((a, b) => a.position - b.position)
                })
                return buckets
            },
        ],
        selectedTask: [
            (s) => [s.tasks, s.selectedTaskId],
            (tasks, selectedTaskId): Task | null =>
                selectedTaskId ? tasks.find((task) => task.id === selectedTaskId) || null : null,
        ],
        hasActiveTasks: [
            (s) => [s.tasks],
            (tasks): boolean =>
                tasks.some(
                    (task) =>
                        task.status === TaskStatus.IN_PROGRESS ||
                        task.status === TaskStatus.TODO ||
                        task.status === TaskStatus.TESTING
                ),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        startPolling: () => {
            if (cache.pollingInterval) {
                clearInterval(cache.pollingInterval)
            }
            cache.pollingInterval = setInterval(() => {
                if (values.hasActiveTasks) {
                    actions.pollForUpdates()
                } else {
                    actions.stopPolling()
                }
            }, 3000) // Poll every 3 seconds
        },
        stopPolling: () => {
            if (cache.pollingInterval) {
                clearInterval(cache.pollingInterval)
                cache.pollingInterval = null
            }
        },
        loadTasksSuccess: () => {
            // Start polling when tasks are loaded if there are active tasks
            if (values.hasActiveTasks && !cache.pollingInterval) {
                actions.startPolling()
            } else if (!values.hasActiveTasks && cache.pollingInterval) {
                actions.stopPolling()
            }
        },
        moveTaskSuccess: () => {
            // Check if polling should start/stop after moving a task
            if (values.hasActiveTasks && !cache.pollingInterval) {
                actions.startPolling()
            } else if (!values.hasActiveTasks && cache.pollingInterval) {
                actions.stopPolling()
            }
        },
        pollForUpdatesSuccess: () => {
            // Stop polling if there are no active tasks
            if (!values.hasActiveTasks) {
                actions.stopPolling()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTasks()
    }),
    beforeUnmount(({ cache }) => {
        if (cache.pollingInterval) {
            clearInterval(cache.pollingInterval)
        }
    }),
])
