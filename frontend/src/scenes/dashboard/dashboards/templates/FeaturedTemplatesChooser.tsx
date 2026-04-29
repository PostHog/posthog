import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { DashboardsListEmptyAiStarterPrompts } from 'scenes/dashboard/dashboardsListEmptyAiStarterPrompts'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardTemplateType,
    SidePanelTab,
    TemplateAvailabilityContext,
} from '~/types'

import BlankDashboardHog from 'public/blank-dashboard-hog.png'

import { runBlankDashboardFlow, runDashboardTemplateClickFlow } from './dashboardTemplateCreationFlows'
import { TemplateItem } from './DashboardTemplateItem'
import { DashboardTemplateItemSkeleton } from './DashboardTemplateItemSkeleton'
import { DashboardTemplateProps, dashboardTemplatesLogic } from './dashboardTemplatesLogic'

export type FeaturedTemplatesChooserProps = Pick<
    DashboardTemplateProps,
    'scope' | 'onItemClick' | 'redirectAfterCreation' | 'availabilityContexts' | 'className'
>

export function FeaturedTemplatesChooser({
    scope = 'default',
    onItemClick,
    redirectAfterCreation = true,
    availabilityContexts,
    className,
}: FeaturedTemplatesChooserProps): JSX.Element {
    const templatesLogic = dashboardTemplatesLogic({ scope, listQuery: { is_featured: true } })
    const { allTemplates, allTemplatesLoading } = useValues(templatesLogic)

    const { isLoading, newDashboardModalVisible } = useValues(newDashboardLogic)
    const {
        setActiveDashboardTemplate,
        createDashboardFromTemplate,
        addDashboard,
        setIsLoading,
        showVariableSelectModal,
    } = useActions(newDashboardLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    const filteredTemplates = useMemo(() => {
        return allTemplates.filter((template) => {
            if (availabilityContexts) {
                return availabilityContexts.some((context) => template.availability_contexts?.includes(context))
            }
            return true
        })
    }, [allTemplates, availabilityContexts])

    const hasFeaturedTiles = filteredTemplates.length > 0

    const handleTemplateClick = (template: DashboardTemplateType): void => {
        runDashboardTemplateClickFlow(template, {
            isLoading,
            newDashboardModalVisible,
            redirectAfterCreation,
            setIsLoading,
            createDashboardFromTemplate,
            showVariableSelectModal,
            setActiveDashboardTemplate,
            onItemClick,
        })
    }

    const showBlankDashboardAction =
        !availabilityContexts || availabilityContexts.includes(TemplateAvailabilityContext.GENERAL)

    const createBlankDashboard = (): void => {
        runBlankDashboardFlow({ isLoading, setIsLoading, addDashboard })
    }

    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor
    )
    const aiBlockedReason =
        !dataProcessingAccepted &&
        (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
    const chipDisabledReason = accessDisabledReason ?? (aiBlockedReason || undefined)

    const onOpenAiWithPrompt = (prompt: string): void => {
        const trimmed = prompt.trim()
        if (trimmed) {
            openSidePanel(SidePanelTab.Max, `!${trimmed}`)
        } else {
            openSidePanel(SidePanelTab.Max)
        }
    }

    return (
        <div className={cn('flex flex-col gap-4 w-full', className)}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full">
                {allTemplatesLoading ? (
                    <>
                        {Array.from({ length: 3 }).map((_, i) => (
                            <DashboardTemplateItemSkeleton key={i} />
                        ))}
                    </>
                ) : !hasFeaturedTiles && showBlankDashboardAction ? (
                    <TemplateItem
                        template={{
                            template_name: 'Blank dashboard',
                            dashboard_description: 'Create a blank dashboard',
                            image_url: BlankDashboardHog,
                        }}
                        onClick={createBlankDashboard}
                        index={0}
                        data-attr="create-dashboard-blank"
                    />
                ) : (
                    filteredTemplates.map((template, index) => (
                        <TemplateItem
                            key={template.id}
                            template={template}
                            onClick={() => handleTemplateClick(template)}
                            index={index}
                            data-attr="create-dashboard-from-featured-template"
                        />
                    ))
                )}
            </div>
            {showBlankDashboardAction && !allTemplatesLoading ? (
                <DashboardsListEmptyAiStarterPrompts
                    chipDisabledReason={chipDisabledReason}
                    onOpenAiWithPrompt={onOpenAiWithPrompt}
                />
            ) : null}
            {showBlankDashboardAction && hasFeaturedTiles ? (
                <LemonButton
                    type="secondary"
                    icon={<IconPlus className="size-3.5" />}
                    onClick={createBlankDashboard}
                    loading={isLoading}
                    data-attr="create-dashboard-blank-from-scratch"
                    className="self-center @min-[48rem]/main-content:self-start"
                >
                    Or start from scratch
                </LemonButton>
            ) : null}
        </div>
    )
}
