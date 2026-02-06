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

interface ProductWithTasks {
    productKey: ProductKey
    name: string
    remainingCount: number
    category: string | undefined
}

export interface ProductSetupPopoverProps {
    visible: boolean
    onClickOutside: () => void
    selectedProduct: ProductKey
    onSelectProduct: (productKey: ProductKey) => void
    children: React.ReactNode
}

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

    const { isProductSelectionLocked } = useValues(globalSetupLogic)
    const { currentTeam } = useValues(teamLogic)
    const savedOnboardingTasks = currentTeam?.onboarding_tasks ?? {}

    const config = getProductSetupConfig(selectedProduct)
    const [hoveredTask, setHoveredTask] = useState<SetupTaskWithState | null>(null)
    const [announcement, setAnnouncement] = useState<string>('')

    // Calculate other products with remaining tasks
    const otherProductsWithTasks = useOtherProductsWithTasks(selectedProduct, savedOnboardingTasks)

    // Hogfetti celebration
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti()
    const previouslyComplete = useRef(isSetupComplete)

    useEffect(() => {
        let hogfettiTimeoutHandlers: NodeJS.Timeout[] = []

        if (isSetupComplete && !previouslyComplete.current && visible) {
            setShowCelebration(true)
            hogfettiTimeoutHandlers = [0, 400, 800].map((delay) => setTimeout(triggerHogfetti, delay))
        }
        if (visible) {
            previouslyComplete.current = isSetupComplete
        }

        return () => {
            hogfettiTimeoutHandlers.forEach((handler) => clearTimeout(handler))
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
        []
    )

    if (!config) {
        return <>{children}</>
    }

    // Separate tasks by type
    const setupTasks = (tasksWithState as SetupTaskWithState[]).filter((t) => t.taskType === 'setup')
    const onboardingTasks = (tasksWithState as SetupTaskWithState[]).filter((t) => t.taskType === 'onboarding')
    const exploreTasks = (tasksWithState as SetupTaskWithState[]).filter((t) => t.taskType === 'explore')

    const productName = config?.title.replace('Get started with ', '') || ''

    const handleTaskClick = (task: SetupTaskWithState): void => {
        if (task.completed || task.skipped || task.lockedReason) {
            return
        }
        runTask(task.id)
    }

    const getTaskTitle = (taskId: SetupTaskId): string => {
        const task = tasksWithState.find((t) => t.id === taskId)
        return task?.title || taskId
    }

    const handleSkip = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        markTaskAsSkipped(taskId)
        setAnnouncement(`${getTaskTitle(taskId)} skipped`)
    }

    const handleUnskip = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        unmarkTaskAsSkipped(taskId)
        setAnnouncement(`${getTaskTitle(taskId)} restored`)
    }

    const handleMarkComplete = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        markTaskAsCompleted(taskId)
        setAnnouncement(`${getTaskTitle(taskId)} marked as complete`)
    }

    const handleUnmarkComplete = (e: React.MouseEvent, taskId: SetupTaskId): void => {
        e.stopPropagation()
        unmarkTaskAsCompleted(taskId)
        setAnnouncement(`${getTaskTitle(taskId)} marked as incomplete`)
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

    const handleSelectSuggestedProduct = (productKey: ProductKey): void => {
        void addProductIntent({
            product_type: productKey,
            intent_context: ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            metadata: {
                from_product: selectedProduct,
            },
        })
        onSelectProduct(productKey)

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
                    <div className="w-80 max-h-[70vh] flex flex-col" role="dialog" aria-label="Quick start guide">
                        {/* Screen reader announcements */}
                        <div className="sr-only" aria-live="polite" aria-atomic="true">
                            {announcement}
                        </div>
                        <PopoverHeader
                            showCelebration={showCelebration}
                            isSetupComplete={isSetupComplete}
                            productName={productName}
                            otherProductsWithTasks={otherProductsWithTasks}
                            isProductSelectionLocked={isProductSelectionLocked}
                            selectedProduct={selectedProduct}
                            onSelectProduct={onSelectProduct}
                            productOptions={productOptions}
                            completedCount={completedCount}
                            totalTasks={totalTasks}
                        />

                        <div className="flex-1 overflow-y-auto" onMouseLeave={() => setHoveredTask(null)}>
                            {isSetupComplete ? (
                                <ProductSuggestions
                                    products={otherProductsWithTasks}
                                    onSelectProduct={handleSelectSuggestedProduct}
                                />
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

                        {hoveredTask && !isSetupComplete && <TaskHoverDescription task={hoveredTask} />}

                        <PopoverFooter
                            isDismissed={isDismissed}
                            onMinimize={handleMinimize}
                            onRestore={handleRestore}
                            selectedProduct={selectedProduct}
                        />
                    </div>
                }
            >
                {children}
            </Popover>
        </>
    )
}

interface PopoverHeaderProps {
    showCelebration: boolean
    isSetupComplete: boolean
    productName: string
    otherProductsWithTasks: ProductWithTasks[]
    isProductSelectionLocked: boolean
    selectedProduct: ProductKey
    onSelectProduct: (productKey: ProductKey) => void
    productOptions: { value: ProductKey; label: string }[]
    completedCount: number
    totalTasks: number
}

function PopoverHeader({
    showCelebration,
    isSetupComplete,
    productName,
    otherProductsWithTasks,
    isProductSelectionLocked,
    selectedProduct,
    onSelectProduct,
    productOptions,
    completedCount,
    totalTasks,
}: PopoverHeaderProps): JSX.Element {
    if (showCelebration || isSetupComplete) {
        return (
            <div className="px-3 py-2 border-b border-border">
                <div className="text-center py-2">
                    <span className="text-lg">🎉</span>
                    <p className="font-semibold text-sm mt-1">You've completed {productName}!</p>
                    {otherProductsWithTasks.length > 0 ? (
                        <p className="text-xs text-muted">Try another product to continue your setup</p>
                    ) : (
                        <p className="text-xs text-muted">You've completed all quick start guides</p>
                    )}
                </div>
            </div>
        )
    }

    return (
        <div className="px-3 py-2 border-b border-border">
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
            <ProgressBar completedCount={completedCount} totalTasks={totalTasks} />
        </div>
    )
}

interface ProgressBarProps {
    completedCount: number
    totalTasks: number
}

function ProgressBar({ completedCount, totalTasks }: ProgressBarProps): JSX.Element {
    const percent = totalTasks > 0 ? (completedCount / totalTasks) * 100 : 0
    return (
        <div className="h-1 bg-border rounded-full mt-2 overflow-hidden">
            <div
                className="h-full bg-success dark:bg-success-light rounded-full transition-all duration-300"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${percent}%` }}
            />
        </div>
    )
}

interface ProductSuggestionsProps {
    products: ProductWithTasks[]
    onSelectProduct: (productKey: ProductKey) => void
}

function ProductSuggestions({ products, onSelectProduct }: ProductSuggestionsProps): JSX.Element {
    if (products.length === 0) {
        return (
            <div className="px-3 py-4 text-center text-sm text-muted">
                You've completed all available quick start guides. Great job!
            </div>
        )
    }

    return (
        <div className="py-2">
            <div className="px-3 py-1">
                <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Continue with</span>
            </div>
            {products.slice(0, 5).map((product) => (
                <ProductSuggestionItem key={product.productKey} product={product} onSelect={onSelectProduct} />
            ))}
        </div>
    )
}

interface ProductSuggestionItemProps {
    product: ProductWithTasks
    onSelect: (productKey: ProductKey) => void
}

function ProductSuggestionItem({ product, onSelect }: ProductSuggestionItemProps): JSX.Element {
    return (
        <div
            role="button"
            tabIndex={0}
            aria-label={`Continue with ${product.name}, ${product.remainingCount} tasks remaining`}
            className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-fill-primary-highlight active:bg-fill-primary-highlight-hover focus-visible:bg-fill-primary-highlight focus-visible:outline-none"
            onClick={() => onSelect(product.productKey)}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect(product.productKey)
                }
            }}
        >
            <IconTarget className="w-4 h-4 text-muted" />
            <span className="flex-1 text-sm">{product.name}</span>
            <span className="text-xs text-muted">{product.remainingCount} tasks</span>
        </div>
    )
}

interface TaskHoverDescriptionProps {
    task: SetupTaskWithState
}

function TaskHoverDescription({ task }: TaskHoverDescriptionProps): JSX.Element {
    return (
        <div className="px-3 py-2 border-t border-border bg-fill-tertiary">
            <span className="text-xs font-medium">{task.title}</span>
            {task.description && typeof task.description === 'string' && (
                <p className="text-xs text-muted mt-0.5 leading-snug">{task.description}</p>
            )}
            {task.lockedReason && (
                <p className="text-xs text-warning mt-1">
                    <strong>Depends on:</strong> {task.lockedReason.replace('Complete "', '').replace('" first', '')}
                </p>
            )}
            {task.requiresManualCompletion && !task.completed && !task.skipped && (
                <p className="text-xs text-muted mt-1 italic">
                    Manual task – {task.docsUrl ? 'click for instructions, then ' : ''}
                    mark as complete when done.
                </p>
            )}
        </div>
    )
}

interface PopoverFooterProps {
    isDismissed: boolean
    onMinimize: () => void
    onRestore: () => void
    selectedProduct: ProductKey
}

function PopoverFooter({ isDismissed, onMinimize, onRestore, selectedProduct }: PopoverFooterProps): JSX.Element {
    return (
        <div className="px-3 py-2 border-t border-border flex items-center justify-between">
            {isDismissed ? (
                <LemonButton type="tertiary" size="xsmall" onClick={onRestore}>
                    Restore
                </LemonButton>
            ) : (
                <LemonButton type="tertiary" size="xsmall" onClick={onMinimize}>
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
    const completedCount = tasks.filter((t) => t.completed || t.skipped).length

    return (
        <div className="py-1" role="group" aria-label={`${title} (${completedCount} of ${tasks.length} complete)`}>
            <div className="px-3 py-1 flex items-center justify-between">
                <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">{title}</span>
                {actionButton}
            </div>
            <div role="list">
                {tasks.map((task) => (
                    <div key={task.id} role="listitem">
                        <TaskItem
                            task={task}
                            onClick={() => onTaskClick(task)}
                            onSkip={onSkip}
                            onUnskip={onUnskip}
                            onMarkComplete={onMarkComplete}
                            onUnmarkComplete={onUnmarkComplete}
                            onHover={onHover}
                        />
                    </div>
                ))}
            </div>
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
    const isClickable = !isDone && !isLocked

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            if (isClickable) {
                onClick()
            }
        }
    }

    const content = (
        <div
            role="button"
            tabIndex={isClickable ? 0 : -1}
            aria-disabled={!isClickable}
            aria-label={`${task.title}${isCompleted ? ' (completed)' : isSkipped ? ' (skipped)' : isLocked ? ' (locked)' : ''}`}
            className={`group flex items-center gap-2 px-3 py-1.5 transition-colors ${
                isDone
                    ? 'opacity-50 hover:opacity-70'
                    : isLocked
                      ? 'opacity-60 cursor-not-allowed'
                      : 'cursor-pointer hover:bg-fill-primary-highlight active:bg-fill-primary-highlight-hover focus-visible:bg-fill-primary-highlight focus-visible:outline-none'
            }`}
            onClick={isClickable ? onClick : undefined}
            onKeyDown={handleKeyDown}
            onMouseEnter={() => onHover?.(task)}
        >
            <TaskStatusIndicator
                isCompleted={isCompleted}
                isSkipped={isSkipped}
                isLocked={isLocked}
                onToggle={(e) => {
                    e.stopPropagation()
                    if (isCompleted && onUnmarkComplete) {
                        onUnmarkComplete(e, task.id)
                    } else if (!isDone && !isLocked && onMarkComplete) {
                        onMarkComplete(e, task.id)
                    }
                }}
            />

            <TaskTitle title={task.title} isDone={isDone} isLocked={isLocked} isSkipped={isSkipped} />

            <TaskActions
                task={task}
                isDone={isDone}
                isLocked={isLocked}
                isCompleted={isCompleted}
                isSkipped={isSkipped}
                onSkip={onSkip}
                onUnskip={onUnskip}
                onMarkComplete={onMarkComplete}
                onUnmarkComplete={onUnmarkComplete}
            />
        </div>
    )

    if (isLocked && task.lockedReason) {
        return <Tooltip title={task.lockedReason}>{content}</Tooltip>
    }

    return content
}

interface TaskStatusIndicatorProps {
    isCompleted: boolean
    isSkipped: boolean
    isLocked: boolean
    onToggle: (e: React.MouseEvent) => void
}

function TaskStatusIndicator({ isCompleted, isSkipped, isLocked, onToggle }: TaskStatusIndicatorProps): JSX.Element {
    return (
        <div
            className="flex-shrink-0 cursor-pointer"
            onClick={onToggle}
            role="checkbox"
            aria-checked={isCompleted}
            aria-label={isCompleted ? 'Mark as incomplete' : isLocked ? 'Locked' : 'Mark as complete'}
            tabIndex={0}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    e.stopPropagation()
                    onToggle(e as unknown as React.MouseEvent)
                }
            }}
        >
            {isCompleted ? (
                <div className="w-4 h-4 rounded-full bg-success dark:bg-success-light flex items-center justify-center">
                    <IconCheck className="w-2.5 h-2.5 text-white" />
                </div>
            ) : isSkipped ? (
                <div className="w-4 h-4 rounded-full border border-border bg-bg-light" />
            ) : isLocked ? (
                <div className="w-4 h-4 rounded-full border border-border bg-bg-light flex items-center justify-center">
                    <IconLock className="w-2.5 h-2.5 text-muted" />
                </div>
            ) : (
                <div className="w-4 h-4 rounded-full border-2 border-border dark:border-white hover:border-success dark:hover:border-success-light hover:bg-fill-success-highlight transition-colors" />
            )}
        </div>
    )
}

interface TaskTitleProps {
    title: string
    isDone: boolean
    isLocked: boolean
    isSkipped: boolean
}

function TaskTitle({ title, isDone, isLocked, isSkipped }: TaskTitleProps): JSX.Element {
    const titleElement = (
        <span className={`flex-1 text-sm ${isDone ? 'line-through text-muted' : isLocked ? 'text-muted' : ''}`}>
            {title}
        </span>
    )

    if (isSkipped) {
        return <Tooltip title="Skipped">{titleElement}</Tooltip>
    }

    return titleElement
}

interface TaskActionsProps {
    task: SetupTaskWithState
    isDone: boolean
    isLocked: boolean
    isCompleted: boolean
    isSkipped: boolean
    onSkip: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onUnskip: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onMarkComplete?: (e: React.MouseEvent, taskId: SetupTaskId) => void
    onUnmarkComplete?: (e: React.MouseEvent, taskId: SetupTaskId) => void
}

function TaskActions({
    task,
    isDone,
    isLocked,
    isCompleted,
    isSkipped,
    onSkip,
    onUnskip,
    onMarkComplete,
    onUnmarkComplete,
}: TaskActionsProps): JSX.Element | null {
    if (isSkipped) {
        return (
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={(e) => onUnskip(e, task.id)}
                    tooltip="Restore this task"
                >
                    Restore
                </LemonButton>
            </div>
        )
    }

    if (isCompleted && onUnmarkComplete) {
        return (
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={(e) => onUnmarkComplete(e, task.id)}
                    tooltip="Mark as incomplete"
                >
                    Undo
                </LemonButton>
            </div>
        )
    }

    if (!isDone && !isLocked) {
        return (
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
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
        )
    }

    return null
}

function useOtherProductsWithTasks(
    selectedProduct: ProductKey,
    savedOnboardingTasks: Record<string, ActivationTaskStatus>
): ProductWithTasks[] {
    return useMemo(() => {
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
}
