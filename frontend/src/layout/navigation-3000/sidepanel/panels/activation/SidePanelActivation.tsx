import { IconCheckCircle, IconChevronRight, IconCollapse, IconExpand, IconLock, IconPlus } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ProfessorHog } from 'lib/components/hedgehogs'
import type { LemonIconProps } from 'lib/lemon-ui/icons'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'

import {
    activationLogic,
    type ActivationSection,
    ActivationTaskType,
} from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { activationTaskContentMap } from './ActivationTaskContent'

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
    buttonText,
}: ActivationTaskType): JSX.Element => {
    const { runTask, markTaskAsSkipped, setExpandedTaskId, setTaskContentHeight } = useActions(activationLogic)
    const { reportActivationSideBarTaskClicked } = useActions(eventUsageLogic)
    const { expandedTaskId, taskContentHeights } = useValues(activationLogic)
    const isActive = !completed && !skipped && !lockedReason
    const hasContent = Boolean(activationTaskContentMap[id])
    const expanded = expandedTaskId === id
    const ContentComponent = hasContent ? activationTaskContentMap[id] : undefined
    const contentHeight = taskContentHeights[id] || 0

    const handleUrlOpen = (url: string): void => {
        try {
            const newWindow = window.open(url, '_blank')
            if (newWindow === null) {
                window.location.href = url
            }
        } catch {
            window.location.href = url
        }
    }

    const handleRowClick = (): void => {
        if (!isActive) {
            return
        }
        if (hasContent) {
            setExpandedTaskId(expanded ? null : id)
        } else {
            reportActivationSideBarTaskClicked(id)
            if (url) {
                handleUrlOpen(url)
            } else {
                runTask(id)
            }
        }
    }

    const handleSkip = (e: React.MouseEvent): void => {
        e.stopPropagation()
        markTaskAsSkipped(id)
    }

    const handleGetStarted = (e: React.MouseEvent): void => {
        e.stopPropagation()
        reportActivationSideBarTaskClicked(id)
        if (url) {
            handleUrlOpen(url)
        } else {
            runTask(id)
        }
    }

    return (
        <li
            className={clsx(
                'p-2 border bg-primary-alt-highlight flex flex-col',
                completed || skipped ? 'line-through opacity-70' : '',
                lockedReason && 'opacity-70'
            )}
        >
            <div
                className={clsx(
                    'flex items-center justify-between gap-2 w-full select-none',
                    isActive && 'cursor-pointer'
                )}
                onClick={handleRowClick}
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
                {isActive && canSkip && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        className="h-6 font-semibold text-muted-alt activation-task-skip"
                        onClick={handleSkip}
                    >
                        Skip
                    </LemonButton>
                )}
            </div>
            {isActive && hasContent && (
                <div
                    className="overflow-hidden transition-[max-height] duration-300"
                    style={{
                        maxHeight: expanded ? `${contentHeight}px` : '0px',
                        marginBottom: expanded ? '8px' : '0px',
                        marginTop: expanded ? '0px' : '0px',
                    }}
                >
                    <div
                        className="pt-2"
                        ref={(el) => {
                            // scrollHeight refers to the height of the content,
                            // including content not visible on the screen due to overflow
                            if (el && expanded && contentHeight !== el.scrollHeight) {
                                setTaskContentHeight(id, el.scrollHeight)
                            }
                        }}
                    >
                        {ContentComponent && <ContentComponent />}
                        <LemonButton type="primary" size="small" className="mt-2" onClick={handleGetStarted}>
                            {buttonText || 'Get started'}
                        </LemonButton>
                    </div>
                </div>
            )}
        </li>
    )
}
