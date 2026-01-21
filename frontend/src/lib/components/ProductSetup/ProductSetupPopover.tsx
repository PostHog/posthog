import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconExternal, IconLock, IconTarget } from '@posthog/icons'
import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { addProductIntent } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'

import { getTreeItemsProducts } from '~/products'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { ActivationTaskStatus } from '~/types'

import { globalSetupLogic } from './globalSetupLogic'
import { productSetupLogic } from './productSetupLogic'
import { PRODUCTS_WITH_SETUP, getProductSetupConfig, getTasksForProduct } from './productSetupRegistry'
import type { SetupTaskId, SetupTaskWithState } from './types'

// Build maps from ProductKey to category and href for sorting and navigation
const productCategoryMap: Partial<Record<ProductKey, string>> = {}
const productHrefMap: Partial<Record<ProductKey, string>> = {}
for (const item of getTreeItemsProducts()) {
    if (item.intents) {
        for (const intent of item.intents) {
            if (item.category) {
                productCategoryMap[intent] = item.category
            }
            if (item.href) {
                productHrefMap[intent] = item.href
            }
        }
    }
}

export interface ProductSetupPopoverProps {
    visible: boolean
    onClickOutside: () => void
    selectedProduct: ProductKey
    onSelectProduct: (productKey: ProductKey) => void
    children: React.ReactNode
}

/**
 * ProductSetupPopover - A popover for product setup tasks with a product selector.
 */
export function ProductSetupPopover({
    visible,
    onClickOutside,
    selectedProduct,
    onSelectProduct,
    children,
}: ProductSetupPopoverProps): JSX.Element {
    const logic = productSetupLogic({ productKey: selectedProduct })
    const { tasksWithState, completedCount, totalTasks, isDismissed, isSetupComplete, showCelebration } =
        useValues(logic)
    const {
        runTask,
        markTaskAsCompleted,
        unmarkTaskAsCompleted,
        markTaskAsSkipped,
        unmarkTaskAsSkipped,
        dismissSetup,
        undismissSetup,
        setShowCelebration,
    } = useActions(logic)

    // Check if the product selection is locked to the current scene
    const { isProductSelectionLocked } = useValues(globalSetupLogic)

    // Get team's onboarding tasks to calculate other products with remaining tasks
    const { currentTeam } = useValues(teamLogic)
    const savedOnboardingTasks = currentTeam?.onboarding_tasks ?? {}

    const config = getProductSetupConfig(selectedProduct)
    const [hoveredTask, setHoveredTask] = useState<SetupTaskWithState | null>(null)

    // Calculate other products with remaining tasks (for suggestions when complete)
    // Sort by category: same category as current product first
    const otherProductsWithTasks = useMemo(() => {
        const currentCategory = productCategoryMap[selectedProduct]

        const products = PRODUCTS_WITH_SETUP.filter((productKey) => {
            if (productKey === selectedProduct) {
                return false
            }
            const tasks = getTasksForProduct(productKey)
            const remainingTasks = tasks.filter((task) => {
                const status = savedOnboardingTasks[task.id]
                return status !== ActivationTaskStatus.COMPLETED && status !== ActivationTaskStatus.SKIPPED
            })
            return remainingTasks.length > 0
        }).map((productKey) => {
            const productConfig = getProductSetupConfig(productKey)
            const tasks = getTasksForProduct(productKey)
            const remainingCount = tasks.filter((task) => {
                const status = savedOnboardingTasks[task.id]
                return status !== ActivationTaskStatus.COMPLETED && status !== ActivationTaskStatus.SKIPPED
            }).length
            return {
                productKey,
                name: productConfig?.title.replace('Get started with ', '') || productKey,
                remainingCount,
                category: productCategoryMap[productKey],
            }
        })

        // Sort: same category first, then alphabetically by name
        return products.sort((a, b) => {
            const aIsSameCategory = a.category === currentCategory
            const bIsSameCategory = b.category === currentCategory
            if (aIsSameCategory && !bIsSameCategory) {
                return -1
            }
            if (!aIsSameCategory && bIsSameCategory) {
                return 1
            }
            return a.name.localeCompare(b.name)
        })
    }, [selectedProduct, savedOnboardingTasks])

    // Hogfetti celebration
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti()
    const previouslyComplete = useRef(isSetupComplete)

    // Detect when setup becomes complete and trigger celebration
    // Only update the ref when visible, so animation can trigger when modal opens after completion
    useEffect(() => {
        if (isSetupComplete && !previouslyComplete.current && visible) {
            setShowCelebration(true)
            ;[0, 400, 800].forEach((delay) => setTimeout(triggerHogfetti, delay))
        }
        if (visible) {
            previouslyComplete.current = isSetupComplete
        }
    }, [isSetupComplete, visible, triggerHogfetti, setShowCelebration])

    // Build product options for the selector
    const productOptions = useMemo(
        () =>
            PRODUCTS_WITH_SETUP.map((productKey) => {
                const productConfig = getProductSetupConfig(productKey)
                return {
                    value: productKey,
                    label: productConfig?.title.replace('Get started with ', '') || productKey,
                }
            }),
        [PRODUCTS_WITH_SETUP, getProductSetupConfig]
    )

    if (!config) {
        return <>{children}</>
    }

    // Separate tasks by type using the taskType field
    const setupTasks = (tasksWithState as SetupTaskWithState[]).filter((t) => t.taskType === 'setup')
    const onboardingTasks = (tasksWithState as SetupTaskWithState[]).filter((t) => t.taskType === 'onboarding')
    const exploreTasks = (tasksWithState as SetupTaskWithState[]).filter((t) => t.taskType === 'explore')

    const handleTaskClick = (task: SetupTaskWithState): void => {
        if (task.completed || task.skipped || task.lockedReason) {
            return
        }
        runTask(task.id)
    }

    const handleSkip = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        markTaskAsSkipped(taskId)
    }

    const handleUnskip = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        unmarkTaskAsSkipped(taskId)
    }

    const handleMarkComplete = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        markTaskAsCompleted(taskId)
    }

    const handleUnmarkComplete = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        unmarkTaskAsCompleted(taskId)
    }

    const handleMinimize = (): void => {
        dismissSetup()
        onClickOutside()
    }

    const handleRestore = (): void => {
        undismissSetup()
    }

    const handleSkipAllExploreTasks = (): void => {
        const taskIdsToSkip = exploreTasks.filter((task) => !task.completed && !task.skipped).map((task) => task.id)
        if (taskIdsToSkip.length > 0) {
            markTaskAsSkipped(taskIdsToSkip)
        }
    }

    // Get product name from config title (e.g., "Get started with Product analytics" -> "Product analytics")
    const productName = config?.title.replace('Get started with ', '') || ''

    const handleSelectSuggestedProduct = (productKey: ProductKey): void => {
        // Track product intent for cross-sell analytics
        void addProductIntent({
            product_type: productKey,
            intent_context: ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            metadata: {
                from_product: selectedProduct,
            },
        })
        onSelectProduct(productKey)

        // Navigate to the product's main page
        const href = productHrefMap[productKey]
        if (href) {
            router.actions.push(href)
        }
    }

    return (
        <>
            <HogfettiComponent />
            <Popover
                visible={visible}
                onClickOutside={onClickOutside}
                placement="bottom-end"
                padded={false}
                overlay={
                    <div className="w-80 max-h-[70vh] flex flex-col">
                        {/* Header with product selector */}
                        <div className="px-3 py-2 border-b border-border">
                            {showCelebration || isSetupComplete ? (
                                <div className="text-center py-2">
                                    <span className="text-lg">🎉</span>
                                    <p className="font-semibold text-sm mt-1">You've completed {productName}!</p>
                                    {otherProductsWithTasks.length > 0 ? (
                                        <p className="text-xs text-muted">Try another product to continue your setup</p>
                                    ) : (
                                        <p className="text-xs text-muted">You've completed all quick start guides</p>
                                    )}
                                </div>
                            ) : (
                                <>
                                    <div className="flex items-center gap-2">
                                        <IconTarget className="text-muted w-4 h-4 flex-shrink-0" />
                                        <span className="font-semibold text-sm">Quick start</span>
                                        {!isProductSelectionLocked && (
                                            <LemonSelect
                                                size="xsmall"
                                                value={selectedProduct}
                                                onChange={(value) => value && onSelectProduct(value)}
                                                options={productOptions}
                                            />
                                        )}
                                        <span className="text-xs text-muted ml-auto">
                                            {completedCount}/{totalTasks}
                                        </span>
                                    </div>
                                    {/* Progress bar */}
                                    <div className="h-1 bg-border rounded-full mt-2 overflow-hidden">
                                        <div
                                            className="h-full bg-success rounded-full transition-all duration-300"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{
                                                width: `${totalTasks > 0 ? (completedCount / totalTasks) * 100 : 0}%`,
                                            }}
                                        />
                                    </div>
                                </>
                            )}
                        </div>

                        {/* Tasks or product suggestions */}
                        <div className="flex-1 overflow-y-auto" onMouseLeave={() => setHoveredTask(null)}>
                            {isSetupComplete ? (
                                // Show other products when current one is complete
                                otherProductsWithTasks.length > 0 ? (
                                    <div className="py-2">
                                        <div className="px-3 py-1">
                                            <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">
                                                Continue with
                                            </span>
                                        </div>
                                        {otherProductsWithTasks.slice(0, 5).map((product) => (
                                            <div
                                                key={product.productKey}
                                                className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-fill-primary-highlight active:bg-fill-primary-highlight-hover"
                                                onClick={() => handleSelectSuggestedProduct(product.productKey)}
                                            >
                                                <IconTarget className="w-4 h-4 text-muted" />
                                                <span className="flex-1 text-sm">{product.name}</span>
                                                <span className="text-xs text-muted">
                                                    {product.remainingCount} tasks
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="px-3 py-4 text-center text-sm text-muted">
                                        You've completed all available quick start guides. Great job!
                                    </div>
                                )
                            ) : (
                                <>
                                    {setupTasks.length > 0 && (
                                        <TaskSection
                                            title="PostHog setup"
                                            tasks={setupTasks}
                                            onTaskClick={handleTaskClick}
                                            onSkip={handleSkip}
                                            onUnskip={handleUnskip}
                                            onMarkComplete={handleMarkComplete}
                                            onUnmarkComplete={handleUnmarkComplete}
                                            onHover={setHoveredTask}
                                        />
                                    )}

                                    {onboardingTasks.length > 0 && (
                                        <TaskSection
                                            title={`Get started with ${productName}`}
                                            tasks={onboardingTasks}
                                            onTaskClick={handleTaskClick}
                                            onSkip={handleSkip}
                                            onUnskip={handleUnskip}
                                            onMarkComplete={handleMarkComplete}
                                            onUnmarkComplete={handleUnmarkComplete}
                                            onHover={setHoveredTask}
                                        />
                                    )}

                                    {exploreTasks.length > 0 && (
                                        <TaskSection
                                            title="Try more"
                                            tasks={exploreTasks}
                                            onTaskClick={handleTaskClick}
                                            onSkip={handleSkip}
                                            onUnskip={handleUnskip}
                                            onMarkComplete={handleMarkComplete}
                                            onUnmarkComplete={handleUnmarkComplete}
                                            onHover={setHoveredTask}
                                            actionButton={
                                                exploreTasks.some((t) => !t.completed && !t.skipped) ? (
                                                    <LemonButton
                                                        type="tertiary"
                                                        size="xsmall"
                                                        onClick={handleSkipAllExploreTasks}
                                                    >
                                                        Skip all
                                                    </LemonButton>
                                                ) : undefined
                                            }
                                        />
                                    )}
                                </>
                            )}
                        </div>

                        {/* Task description - shown on hover (not in completion view) */}
                        {hoveredTask && !isSetupComplete && (
                            <div className="px-3 py-2 border-t border-border bg-fill-tertiary">
                                <span className="text-xs font-medium">{hoveredTask.title}</span>
                                {hoveredTask.description && typeof hoveredTask.description === 'string' && (
                                    <p className="text-xs text-muted mt-0.5 leading-snug">{hoveredTask.description}</p>
                                )}
                                {hoveredTask.lockedReason && (
                                    <p className="text-xs text-warning mt-1">
                                        <strong>Depends on:</strong>{' '}
                                        {hoveredTask.lockedReason.replace('Complete "', '').replace('" first', '')}
                                    </p>
                                )}
                                {hoveredTask.requiresManualCompletion &&
                                    !hoveredTask.completed &&
                                    !hoveredTask.skipped && (
                                        <p className="text-xs text-muted mt-1 italic">
                                            Manual task – {hoveredTask.docsUrl ? 'click for instructions, then ' : ''}
                                            mark as complete when done.
                                        </p>
                                    )}
                            </div>
                        )}

                        {/* Footer */}
                        <div className="px-3 py-2 border-t border-border flex items-center justify-between">
                            {isDismissed ? (
                                <LemonButton type="tertiary" size="xsmall" onClick={handleRestore}>
                                    Restore
                                </LemonButton>
                            ) : (
                                <LemonButton type="tertiary" size="xsmall" onClick={handleMinimize}>
                                    Minimize
                                </LemonButton>
                            )}
                            <Link
                                to={`https://posthog.com/docs/${selectedProduct.replace(/_/g, '-')}`}
                                target="_blank"
                                className="text-xs text-muted hover:text-primary"
                            >
                                View docs
                            </Link>
                        </div>
                    </div>
                }
            >
                {children}
            </Popover>
        </>
    )
}

interface TaskSectionProps {
    title: string
    tasks: SetupTaskWithState[]
    onTaskClick: (task: SetupTaskWithState) => void
    onSkip: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onUnskip: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onMarkComplete?: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onUnmarkComplete?: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onHover?: (task: SetupTaskWithState | null) => void
    /** Optional action button to show next to the section title */
    actionButton?: React.ReactNode
}

function TaskSection({
    title,
    tasks,
    onTaskClick,
    onSkip,
    onUnskip,
    onMarkComplete,
    onUnmarkComplete,
    onHover,
    actionButton,
}: TaskSectionProps): JSX.Element {
    return (
        <div className="py-1">
            <div className="px-3 py-1 flex items-center justify-between">
                <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">{title}</span>
                {actionButton}
            </div>
            {tasks.map((task) => (
                <TaskItem
                    key={task.id}
                    task={task}
                    onClick={() => onTaskClick(task)}
                    onSkip={onSkip}
                    onUnskip={onUnskip}
                    onMarkComplete={onMarkComplete}
                    onUnmarkComplete={onUnmarkComplete}
                    onHover={onHover}
                />
            ))}
        </div>
    )
}

interface TaskItemProps {
    task: SetupTaskWithState
    onClick: () => void
    onSkip: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onUnskip: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onMarkComplete?: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onUnmarkComplete?: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onHover?: (task: SetupTaskWithState | null) => void
}

function TaskItem({
    task,
    onClick,
    onSkip,
    onUnskip,
    onMarkComplete,
    onUnmarkComplete,
    onHover,
}: TaskItemProps): JSX.Element {
    const isCompleted = task.completed
    const isSkipped = task.skipped
    const isDone = isCompleted || isSkipped
    const isLocked = !!task.lockedReason

    const titleElement = (
        <span className={`flex-1 text-sm ${isDone ? 'line-through text-muted' : isLocked ? 'text-muted' : ''}`}>
            {task.title}
        </span>
    )

    const isClickable = !isDone && !isLocked

    const content = (
        <div
            className={`group flex items-center gap-2 px-3 py-1.5 transition-colors ${
                isDone
                    ? 'opacity-50 hover:opacity-70'
                    : isLocked
                      ? 'opacity-60 cursor-not-allowed'
                      : 'cursor-pointer hover:bg-fill-primary-highlight active:bg-fill-primary-highlight-hover'
            }`}
            onClick={isClickable ? onClick : undefined}
            onMouseEnter={() => onHover?.(task)}
        >
            {/* Status indicator - clickable to mark complete/uncomplete */}
            <div
                className="flex-shrink-0 cursor-pointer"
                onClick={(e) => {
                    e.stopPropagation()
                    if (isCompleted && onUnmarkComplete) {
                        onUnmarkComplete(e, task.id)
                    } else if (!isDone && !isLocked && onMarkComplete) {
                        onMarkComplete(e, task.id)
                    }
                }}
            >
                {isCompleted ? (
                    <div className="w-4 h-4 rounded-full bg-success flex items-center justify-center">
                        <IconCheck className="w-2.5 h-2.5 text-white" />
                    </div>
                ) : isSkipped ? (
                    <div className="w-4 h-4 rounded-full border border-border bg-bg-light" />
                ) : isLocked ? (
                    <div className="w-4 h-4 rounded-full border border-border bg-bg-light flex items-center justify-center">
                        <IconLock className="w-2.5 h-2.5 text-muted" />
                    </div>
                ) : (
                    <div className="w-4 h-4 rounded-full border-2 border-border hover:border-success hover:bg-success/10 transition-colors" />
                )}
            </div>

            {isSkipped ? <Tooltip title="Skipped">{titleElement}</Tooltip> : titleElement}

            {isSkipped && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={(e) => onUnskip(e, task.id)}
                        tooltip="Restore this task"
                    >
                        Restore
                    </LemonButton>
                </div>
            )}

            {isCompleted && onUnmarkComplete && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={(e) => onUnmarkComplete(e, task.id)}
                        tooltip="Mark as incomplete"
                    >
                        Undo
                    </LemonButton>
                </div>
            )}

            {!isDone && !isLocked && (
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {onMarkComplete && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={(e) => onMarkComplete(e, task.id)}
                            tooltip="Mark as complete"
                        >
                            <IconCheck className="w-3 h-3" />
                        </LemonButton>
                    )}
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={(e) => onSkip(e, task.id)}
                        tooltip={task.skipWarning || 'Skip this task'}
                    >
                        Skip
                    </LemonButton>
                    {task.docsUrl && <IconExternal className="w-3.5 h-3.5 text-muted" />}
                </div>
            )}
        </div>
    )

    if (isLocked && task.lockedReason) {
        return <Tooltip title={task.lockedReason}>{content}</Tooltip>
    }

    return content
}
