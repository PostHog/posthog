import { IconCheckCircle, IconChevronRight, IconCollapse, IconExpand, IconLock, IconPlus } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ProfessorHog } from 'lib/components/hedgehogs'
import type { LemonIconProps } from 'lib/lemon-ui/icons'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import {
    activationLogic,
    type ActivationSection,
    ActivationTaskType,
} from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

export const SidePanelActivation = (): JSX.Element | null => {
    const { completionPercent, sections, isReady, showHiddenSections, hasHiddenSections } = useValues(activationLogic)
    const { toggleShowHiddenSections } = useActions(activationLogic)

    if (!isReady) {
        return null
    }

    return (
        <>
            <SidePanelPaneHeader title="Quick start" />
            <div className="py-4 deprecated-space-y-2 overflow-y-auto no-scrollbar">
                <div className="flex flex-col px-4 deprecated-space-y-2">
                    <div className="flex">
                        <p>
                            Use our Quick Start guide to learn about everything PostHog can do for you and your product.
                        </p>
                        <ProfessorHog className="max-h-full w-20 object-contain" />
                    </div>
                    <div className="flex items-center justify-center gap-2 w-full">
                        <LemonProgress
                            percent={completionPercent}
                            size="medium"
                            bgColor="var(--bg-3000)"
                            strokeColor="var(--success)"
                            className="w-full stroke-opacity-80 h-2"
                        />
                        <span className="font-medium text-muted-alt">{completionPercent}%</span>
                    </div>
                </div>
                <div className="divide-y">
                    {sections
                        .filter((section) => section.visible)
                        .map((section) => (
                            <div className="px-4" key={section.key}>
                                <ActivationSectionComponent sectionKey={section.key} section={section} />
                            </div>
                        ))}
                </div>
                {hasHiddenSections && (
                    <div className="w-full">
                        <button
                            className="px-4 py-2 flex items-center justify-between w-full cursor-pointer"
                            onClick={() => toggleShowHiddenSections()}
                            role="button"
                            aria-expanded={showHiddenSections}
                        >
                            <h4 className="font-semibold text-[16px]">All products</h4>
                            {showHiddenSections ? (
                                <IconCollapse className="h-5 w-5" />
                            ) : (
                                <IconExpand className="h-5 w-5" />
                            )}
                        </button>
                        <div className="divide-y">
                            {showHiddenSections &&
                                sections
                                    .filter((section) => !section.visible)
                                    .map((section) => (
                                        <div className="px-4" key={section.key}>
                                            <ActivationSectionComponent sectionKey={section.key} section={section} />
                                        </div>
                                    ))}
                        </div>
                    </div>
                )}
            </div>
        </>
    )
}

export const SidePanelActivationIcon = ({
    className,
    size = 20,
}: {
    className?: LemonIconProps['className']
    size?: number
}): JSX.Element => {
    const { activeTasks, completionPercent } = useValues(activationLogic)

    return (
        <LemonProgressCircle
            progress={completionPercent / 100}
            strokePercentage={0.15}
            size={size}
            className={clsx(activeTasks.length > 0 ? 'text-accent' : 'text-muted-alt', className)}
        >
            <span className="text-xs font-semibold">{activeTasks.length}</span>
        </LemonProgressCircle>
    )
}

const ActivationSectionComponent = ({
    sectionKey,
    section,
}: {
    sectionKey: ActivationSection
    section: (typeof activationLogic.values.sections)[number]
}): JSX.Element | null => {
    const { tasks } = useValues(activationLogic)
    const { toggleSectionOpen, addIntentForSection } = useActions(activationLogic)

    const sectionTasks = tasks.filter((task) => task.section === sectionKey)

    if (sectionTasks.length === 0) {
        return null
    }

    const handleClick = (): void => {
        if (section.visible) {
            toggleSectionOpen(sectionKey)
        }
    }

    const handleAddProduct = (): void => {
        if (!section.visible) {
            addIntentForSection(sectionKey)
        }
        if (!section.open) {
            toggleSectionOpen(sectionKey)
        }
    }

    const itemsCompleted = sectionTasks.filter((task) => task.completed).length
    const totalItems = sectionTasks.length

    return (
        <div className="py-3">
            <button
                className={clsx(
                    'flex items-center justify-between select-none w-full',
                    section.visible && 'cursor-pointer'
                )}
                onClick={section.visible ? handleClick : undefined}
                role="button"
                aria-expanded={section.open}
            >
                <div className="flex items-center gap-2">
                    {section.icon}
                    <h4 className="m-0 font-semibold text-[16px]">{section.title}</h4>
                </div>
                <div className="flex items-center gap-2">
                    {section.visible && (
                        <span className="text-sm text-muted-alt font-medium">
                            {itemsCompleted} of {totalItems} complete
                        </span>
                    )}
                    {section.visible ? (
                        <IconChevronRight className={clsx('h-4 w-4', section.open && 'rotate-90')} />
                    ) : (
                        <LemonButton
                            icon={<IconPlus className="h-4 w-4" />}
                            onClick={handleAddProduct}
                            size="xsmall"
                            type="secondary"
                        >
                            Add
                        </LemonButton>
                    )}
                </div>
            </button>
            {section.visible && section.open && (
                <ul className="deprecated-space-y-2 mt-2">
                    {sectionTasks.map((task: ActivationTaskType) => (
                        <ActivationTask key={task.id} {...task} />
                    ))}
                </ul>
            )}
        </div>
    )
}

const ActivationTask = ({
    id,
    title,
    completed,
    skipped,
    canSkip,
    lockedReason,
    url,
}: ActivationTaskType): JSX.Element => {
    const { runTask, markTaskAsSkipped } = useActions(activationLogic)
    const { reportActivationSideBarTaskClicked } = useActions(eventUsageLogic)

    const handleClick = (): void => {
        reportActivationSideBarTaskClicked(id)
        if (url) {
            try {
                const newWindow = window.open(url, '_blank')
                if (newWindow === null) {
                    // Handle popup blocked case
                    window.location.href = url
                }
            } catch (e) {
                // Fallback to regular navigation
                window.location.href = url
            }
        } else {
            runTask(id)
        }
    }

    const canInteract = !completed && !skipped && !lockedReason

    return (
        <li
            className={clsx(
                'p-2 border bg-primary-alt-highlight flex items-center justify-between gap-2 select-none',
                completed || skipped ? 'line-through opacity-70' : '',
                canInteract && 'cursor-pointer',
                lockedReason && 'opacity-70'
            )}
            onClick={canInteract ? handleClick : undefined}
        >
            <div className="flex items-center gap-2">
                {completed ? (
                    <IconCheckCircle className="h-6 w-6 text-success" />
                ) : lockedReason ? (
                    <Tooltip title={lockedReason}>
                        <IconLock className="h-6 w-6 text-muted-alt" />
                    </Tooltip>
                ) : (
                    <div className="rounded-full border-2 w-5 h-5 border-muted-alt" />
                )}
                <p className="m-0 font-semibold">{title}</p>
            </div>

            {canInteract && canSkip && (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    className="h-6 font-semibold text-muted-alt"
                    onClick={(e) => {
                        e.stopPropagation()
                        markTaskAsSkipped(id)
                    }}
                >
                    Skip
                </LemonButton>
            )}
        </li>
    )
}
