import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { GraphsHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

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
import { dashboardLogic } from './dashboardLogic'
import { EmptyDashboardAiStarterPrompts } from './emptyDashboardAiStarterPrompts'

const DASHBOARD_DOCS_URL = 'https://posthog.com/docs/product-analytics/dashboards'

const BASE_TEXT =
    'A simple first step is to add an insight from your library. Over time this becomes the home for the data you care about most.'

function DashboardEmptyActions({
    canEdit,
    dashboard,
    aiDisabledReason,
    onAddInsight,
    push,
    onOpenAiWithPrompt,
}: {
    canEdit: boolean
    dashboard: DashboardType<QueryBasedInsightModel> | null | undefined
    aiDisabledReason: string | false
    onAddInsight: () => void
    push: (path: string) => void
    onOpenAiWithPrompt: (prompt: string) => void
}): JSX.Element {
    const chipDisabledReason = !canEdit ? DASHBOARD_CANNOT_EDIT_MESSAGE : aiDisabledReason || undefined

    const addInsightButton = (
        <LemonButton
            data-attr="dashboard-add-graph-header"
            onClick={onAddInsight}
            type="primary"
            icon={<IconPlus />}
            disabledReason={canEdit ? null : DASHBOARD_CANNOT_EDIT_MESSAGE}
            sideAction={
                dashboard
                    ? {
                          dropdown: {
                              placement: 'bottom-end',
                              overlay: (
                                  <AccessControlAction
                                      resourceType={AccessControlResourceType.Dashboard}
                                      minAccessLevel={AccessControlLevel.Editor}
                                      userAccessLevel={dashboard.user_access_level}
                                  >
                                      <LemonButton
                                          fullWidth
                                          onClick={() => {
                                              push(urls.dashboardTextTile(dashboard.id, 'new'))
                                          }}
                                          data-attr="add-text-tile-to-dashboard"
                                      >
                                          Add text card
                                      </LemonButton>
                                  </AccessControlAction>
                              ),
                          },
                          disabled: false,
                          'data-attr': 'dashboard-add-dropdown',
                      }
                    : undefined
            }
        >
            Get started
        </LemonButton>
    )

    return (
        <div className="flex flex-col gap-4 w-full max-w-full">
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 @min-[48rem]/main-content:justify-start">
                {addInsightButton}
            </div>
            <EmptyDashboardAiStarterPrompts
                dashboardId={dashboard?.id}
                chipDisabledReason={chipDisabledReason}
                onOpenAiWithPrompt={onOpenAiWithPrompt}
            />
        </div>
    )
}

function EmptyDashboardContent({ canEdit }: { canEdit: boolean }): JSX.Element {
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)
    const { push } = useActions(router)
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
            productName="Dashboard"
            thingName="insight"
            titleOverride="So empty. So much potential."
            description={BASE_TEXT}
            isEmpty={true}
            customHog={GraphsHog}
            hogLayout="responsive"
            useMainContentContainerQueries={true}
            docsURL={DASHBOARD_DOCS_URL}
            className="mt-2 mb-2 px-4 @min-[40rem]/main-content:px-8 py-4 @min-[48rem]/main-content:py-14"
            contentClassName="[&>div:last-child]:!mt-4"
            actionElementOverride={
                <DashboardEmptyActions
                    canEdit={canEdit}
                    dashboard={dashboard}
                    aiDisabledReason={aiDisabledReason}
                    onAddInsight={showAddInsightToDashboardModal}
                    push={push}
                    onOpenAiWithPrompt={onOpenAiWithPrompt}
                />
            }
        />
    )
}

export function EmptyDashboardComponent({ loading, canEdit }: { loading: boolean; canEdit: boolean }): JSX.Element {
    if (loading) {
        return (
            <div className="flex justify-center items-center min-h-[24rem] py-8">
                <Spinner />
            </div>
        )
    }

    return <EmptyDashboardContent canEdit={canEdit} />
}
