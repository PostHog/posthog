import { useActions, useValues } from 'kea'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import { IconChevronDown, IconPlus } from '@posthog/icons'
import { DashboardLoadingState } from '@posthog/products-dashboards/frontend/components/DashboardLoadingState/DashboardLoadingState'

import { pngHoggie } from 'lib/brand/hoggies'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AccessControlLevel, AccessControlResourceType, DashboardType, SidePanelTab } from '~/types'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DashboardAiPromptComposer } from './DashboardAiPromptComposer'
import { DASHBOARD_CANNOT_EDIT_MESSAGE } from './DashboardHeader'
import { getAddTileMenuItems } from './DashboardHeaderActions'
import { dashboardLogic } from './dashboardLogic'

const HedgehogChart = pngHoggie(chartPng)

const BASE_TEXT = 'Add a chart from your library, or start with a question about what matters to your product.'

function DashboardEmptyActions({
    canEdit,
    dashboard,
    aiDisabledReason,
    onAddInsight,
    onAddText,
    onAddImage,
    onAddButton,
    onAddWidget,
    onOpenAiWithPrompt,
}: {
    canEdit: boolean
    dashboard: DashboardType | null | undefined
    aiDisabledReason: string | false
    onAddInsight: () => void
    onAddText: () => void
    onAddImage: () => void
    onAddButton: () => void
    onAddWidget: () => void
    onOpenAiWithPrompt: (prompt: string) => void
}): JSX.Element {
    const { reportDashboardEmptyAddChartClicked, reportDashboardEmptyWebAnalyticsClicked } = useActions(eventUsageLogic)
    const chipDisabledReason = !canEdit ? DASHBOARD_CANNOT_EDIT_MESSAGE : aiDisabledReason || undefined
    const handleAddInsight = (): void => {
        reportDashboardEmptyAddChartClicked(dashboard?.id)
        onAddInsight()
    }

    return (
        <div className="flex flex-col gap-4 w-full max-w-full">
            {!aiDisabledReason && (
                <DashboardAiPromptComposer
                    dashboardId={dashboard?.id}
                    disabledReason={chipDisabledReason}
                    onOpenAiWithPrompt={onOpenAiWithPrompt}
                />
            )}
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 @min-[48rem]/main-content:justify-start">
                {dashboard && (
                    <>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Dashboard}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={dashboard.user_access_level}
                        >
                            <LemonButton
                                data-attr="dashboard-add-graph-header"
                                type="primary"
                                icon={<IconPlus />}
                                onClick={handleAddInsight}
                                disabledReason={canEdit ? null : DASHBOARD_CANNOT_EDIT_MESSAGE}
                            >
                                Add a chart
                            </LemonButton>
                        </AccessControlAction>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Dashboard}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={dashboard.user_access_level}
                        >
                            {({ disabledReason }) => (
                                <LemonMenu
                                    placement="bottom-start"
                                    items={getAddTileMenuItems({
                                        onAddInsight: handleAddInsight,
                                        onAddText,
                                        onAddImage,
                                        onAddButton,
                                        setAddWidgetModalOpen: onAddWidget,
                                    })}
                                >
                                    <LemonButton
                                        type="secondary"
                                        data-attr="dashboard-add-dropdown"
                                        sideIcon={<IconChevronDown />}
                                        disabledReason={canEdit ? disabledReason : DASHBOARD_CANNOT_EDIT_MESSAGE}
                                    >
                                        Build it myself
                                    </LemonButton>
                                </LemonMenu>
                            )}
                        </AccessControlAction>
                    </>
                )}
                <LemonButton
                    type="secondary"
                    to={urls.webAnalytics()}
                    onClick={() => reportDashboardEmptyWebAnalyticsClicked(dashboard?.id)}
                >
                    or View Web Analytics
                </LemonButton>
            </div>
        </div>
    )
}

function EmptyDashboardContent({ canEdit }: { canEdit: boolean }): JSX.Element {
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)
    const { setAddWidgetModalOpen, openTextTileModal, openImageTileModal, openButtonTileModal } =
        useActions(dashboardLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const aiDisabledReason =
        !dataProcessingAccepted &&
        (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')

    const onOpenAiWithPrompt = (prompt: string): void => {
        const trimmed = prompt.trim()
        if (trimmed) {
            // `!` = auto-send after mount (parseCommandString in maxLogic); same as #panel=max:!…
            openSidePanel(SidePanelTab.Max, `!${trimmed}`)
        } else {
            openSidePanel(SidePanelTab.Max)
        }
    }

    return (
        <ProductIntroduction
            thingName="insight"
            titleOverride="Build your dashboard"
            description={dataProcessingAccepted ? BASE_TEXT : 'Add a chart from your library.'}
            isEmpty={true}
            customHog={HedgehogChart}
            hogLayout="responsive"
            useMainContentContainerQueries={true}
            className="mt-2 mb-2 py-4 @min-[48rem]/main-content:py-14"
            contentClassName="[&>div:last-child]:!mt-4"
            actionElementOverride={
                <DashboardEmptyActions
                    canEdit={canEdit}
                    dashboard={dashboard}
                    aiDisabledReason={aiDisabledReason}
                    onAddInsight={showAddInsightToDashboardModal}
                    onAddText={openTextTileModal}
                    onAddImage={openImageTileModal}
                    onAddButton={openButtonTileModal}
                    onAddWidget={() => setAddWidgetModalOpen(true)}
                    onOpenAiWithPrompt={onOpenAiWithPrompt}
                />
            }
        />
    )
}

export function EmptyDashboardComponent({ loading, canEdit }: { loading: boolean; canEdit: boolean }): JSX.Element {
    if (loading) {
        return <DashboardLoadingState />
    }

    return <EmptyDashboardContent canEdit={canEdit} />
}
