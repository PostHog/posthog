import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import { IconListCheck, IconPlus } from '@posthog/icons'
import { DashboardLoadingState } from '@posthog/products-dashboards/frontend/components/DashboardLoadingState/DashboardLoadingState'

import { pngHoggie } from 'lib/brand/hoggies'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardType,
    QueryBasedInsightModel,
    SidePanelTab,
} from '~/types'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DASHBOARD_CANNOT_EDIT_MESSAGE } from './DashboardHeader'
import { getAddTileMenuItems } from './DashboardHeaderActions'
import { dashboardLogic } from './dashboardLogic'
import { dashboardOnboardingChecklistLogic } from './dashboardOnboardingChecklistLogic'

const HedgehogChart = pngHoggie(chartPng)

const DASHBOARD_DOCS_URL = 'https://posthog.com/docs/product-analytics/dashboards'

const BASE_TEXT =
    'A simple first step is to add an insight from your library. Over time this becomes the home for the data you care about most.'

function DashboardEmptyActions({
    canEdit,
    dashboard,
    dashboardWidgetsEnabled,
    onAddInsight,
    onAddWidget,
    push,
}: {
    canEdit: boolean
    dashboard: DashboardType<QueryBasedInsightModel> | null | undefined
    dashboardWidgetsEnabled: boolean
    onAddInsight: () => void
    onAddWidget: () => void
    push: (path: string) => void
}): JSX.Element {
    const { active: onboardingChecklistActive } = useValues(
        dashboardOnboardingChecklistLogic({ dashboardId: dashboard?.id ?? -1 })
    )
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div className="flex flex-col gap-4 w-full max-w-full">
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 @min-[48rem]/main-content:justify-start">
                {dashboard && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Dashboard}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={dashboard.user_access_level}
                    >
                        <LemonButton
                            data-attr="dashboard-add-graph-header"
                            type="primary"
                            icon={<IconPlus />}
                            onClick={onAddInsight}
                            disabledReason={canEdit ? null : DASHBOARD_CANNOT_EDIT_MESSAGE}
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-end',
                                    overlay: (
                                        <LemonMenuOverlay
                                            items={getAddTileMenuItems({
                                                dashboardId: dashboard.id,
                                                dashboardWidgetsEnabled,
                                                onAddInsight,
                                                push,
                                                setAddWidgetModalOpen: onAddWidget,
                                            })}
                                        />
                                    ),
                                },
                                disabled: !canEdit,
                                disabledReason: canEdit ? null : DASHBOARD_CANNOT_EDIT_MESSAGE,
                                'data-attr': 'dashboard-add-dropdown',
                            }}
                        >
                            Get started
                        </LemonButton>
                    </AccessControlAction>
                )}
                {onboardingChecklistActive && dashboard?.id && (
                    <LemonButton
                        type="secondary"
                        icon={<IconListCheck />}
                        onClick={() => openSidePanel(SidePanelTab.DashboardOnboarding, String(dashboard.id))}
                        data-attr="dashboard-onboarding-open"
                    >
                        Onboarding checklist
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function EmptyDashboardContent({ canEdit }: { canEdit: boolean }): JSX.Element {
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { dashboard, dashboardWidgetsEnabled } = useValues(dashboardLogic)
    const { setAddWidgetModalOpen } = useActions(dashboardLogic)
    const { push } = useActions(router)
    return (
        <ProductIntroduction
            productName="Dashboard"
            thingName="insight"
            titleOverride="So empty. So much potential."
            description={BASE_TEXT}
            isEmpty={true}
            customHog={HedgehogChart}
            hogLayout="responsive"
            useMainContentContainerQueries={true}
            docsURL={DASHBOARD_DOCS_URL}
            className="mt-2 mb-2 px-4 @min-[40rem]/main-content:px-8 py-4 @min-[48rem]/main-content:py-14"
            contentClassName="[&>div:last-child]:!mt-4"
            actionElementOverride={
                <DashboardEmptyActions
                    canEdit={canEdit}
                    dashboard={dashboard}
                    dashboardWidgetsEnabled={dashboardWidgetsEnabled}
                    onAddInsight={showAddInsightToDashboardModal}
                    onAddWidget={() => setAddWidgetModalOpen(true)}
                    push={push}
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
