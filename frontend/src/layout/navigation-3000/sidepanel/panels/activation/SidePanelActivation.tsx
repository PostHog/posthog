import {
    IconCheckCircle,
    IconChevronRight,
    IconDatabase,
    IconFeatures,
    IconGraph,
    IconMessage,
    IconRewindPlay,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ProfessorHog } from 'lib/components/hedgehogs'
import type { LemonIconProps } from 'lib/lemon-ui/icons'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'

import {
    activationLogic,
    ActivationSection,
    ActivationTaskType,
} from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

const ACTIVATION_SECTIONS: Record<ActivationSection, { title: string; icon: JSX.Element }> = {
    [ActivationSection.QuickStart]: {
        title: 'Get Started',
        icon: <IconFeatures className="h-5 w-5 text-accent-primary" />,
    },
    [ActivationSection.ProductAnalytics]: {
        title: 'Product analytics',
        icon: <IconGraph className="h-5 w-5 text-brand-blue" />,
    },
    [ActivationSection.SessionReplay]: {
        title: 'Session replay',
        icon: <IconRewindPlay className="h-5 w-5 text-brand-yellow" />,
    },
    [ActivationSection.FeatureFlags]: {
        title: 'Feature flags',
        icon: <IconToggle className="h-5 w-5 text-seagreen" />,
    },
    [ActivationSection.Experiments]: {
        title: 'Experiments',
        icon: <IconTestTube className="h-5 w-5 text-purple" />,
    },
    [ActivationSection.DataPipelines]: {
        title: 'Data pipelines',
        icon: <IconDatabase className="h-5 w-5 text-lilac" />,
    },
    [ActivationSection.Surveys]: {
        title: 'Surveys',
        icon: <IconMessage className="h-5 w-5 text-salmon" />,
    },
}

export const SidePanelActivation = (): JSX.Element => {
    const { completionPercent } = useValues(activationLogic)

    return (
        <>
            <SidePanelPaneHeader title="Quick start" />
            <div className="py-4 space-y-2 overflow-y-auto">
                <div className="flex flex-col px-4 space-y-2">
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
                <div className="divide-y divide-muted-alt">
                    {Object.entries(ACTIVATION_SECTIONS).map(([sectionKey, section]) => (
                        <div className="px-4" key={sectionKey}>
                            <ActivationSectionComponent
                                sectionKey={sectionKey as ActivationSection}
                                section={section}
                            />
                        </div>
                    ))}
                </div>
            </div>
        </>
    )
}

export const SidePanelActivationIcon = ({ className }: { className: LemonIconProps['className'] }): JSX.Element => {
    const { activeTasks, completionPercent } = useValues(activationLogic)

    return (
        <LemonProgressCircle
            progress={completionPercent / 100}
            strokePercentage={0.15}
            size={20}
            className={clsx('text-accent-primary', className)}
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
    section: any
}): JSX.Element | null => {
    const { activeTasks, completedTasks } = useValues(activationLogic)
    const [isOpen, setIsOpen] = useState(true)

    const tasks = [...activeTasks, ...completedTasks].filter((task) => task.section === sectionKey)

    if (tasks.length === 0) {
        return null
    }

    const itemsCompleted = tasks.filter((task) => task.completed).length
    const totalItems = tasks.length

    return (
        <div className="py-3">
            <div
                className="flex items-center justify-between cursor-pointer select-none"
                onClick={() => setIsOpen(!isOpen)}
            >
                <div className="flex items-center gap-2">
                    {section.icon}
                    <h4 className="m-0 font-semibold text-[16px]">{section.title}</h4>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-alt font-medium">
                        {itemsCompleted} of {totalItems} complete
                    </span>
                    <IconChevronRight className={clsx('h-4 w-4', isOpen && 'rotate-90')} />
                </div>
            </div>
            {isOpen && (
                <ul className="space-y-2 mt-2">
                    {tasks.map((task: ActivationTaskType) => (
                        <ActivationTask key={task.id} {...task} />
                    ))}
                </ul>
            )}
        </div>
    )
}

const ActivationTask = ({ id, title, completed, skipped, url }: ActivationTaskType): JSX.Element => {
    const { runTask } = useActions(activationLogic)
    const { reportActivationSideBarTaskClicked } = useActions(eventUsageLogic)

    const handleClick = (): void => {
        reportActivationSideBarTaskClicked(id)
        if (url) {
            window.open(url, '_blank')
        } else {
            runTask(id)
        }
    }

    return (
        <li
            className={clsx(
                'p-2 border bg-primary-alt-highlight flex items-center justify-between gap-2 select-none',
                completed && 'line-through opacity-70',
                !completed && !skipped && 'cursor-pointer'
            )}
            onClick={!completed && !skipped ? handleClick : undefined}
        >
            <div className="flex items-center gap-2">
                {completed ? (
                    <IconCheckCircle className="h-6 w-6 text-success" />
                ) : (
                    <div className="rounded-full border-2 w-5 h-5 border-muted-alt" />
                )}
                <p className="m-0 font-semibold">{title}</p>
            </div>
            {!completed && !skipped && <IconChevronRight className="h-6 font-semibold text-muted-alt" />}

            {/* <div className="flex-1">
                {!completed && !skipped && <p className="text-xs text-gray-500">{content}</p>}
            </div>
            {canSkip && !completed && !skipped && (
                <LemonButton icon={<IconX />} tooltip="Skip task" onClick={() => skipTask(id)} />
            )}
            {!completed && !skipped && (
                <LemonButton onClick={handleClick} to={url} targetBlank={!!url}  icon={<IconPlay />}>
                    {url ? 'Go' : 'Start'}
                </LemonButton>
            )} */}
        </li>
    )
}
