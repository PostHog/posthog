import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus, IconSparkles } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { GraphsHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
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

const DASHBOARD_DOCS_URL = 'https://posthog.com/docs/product-analytics/dashboards'

const BASE_TEXT =
    'A simple first step is to add an insight from your library. Over time this becomes the home for the data you care about most.'

const DASHBOARD_AI_PROMPT_CHIPS: readonly { id: string; label: string; prompt: string }[] = [
    {
        id: 'landing_performance',
        label: 'See which campaigns and landing pages actually convert',
        prompt: 'Build a dashboard for landing page performance over the last 30 days: pageview or $pageview by path / UTM campaign, bounce proxy (single-page sessions), conversion to a primary goal event (e.g. signed up or book a demo), and session replay links for top paths with drop-off. Add insights I can save to this dashboard.',
    },
    {
        id: 'core_web_metrics',
        label: 'Know who visits, which pages matter, and where the site struggles',
        prompt: 'Give me a core web metrics dashboard: traffic (DAU/visitors), top pages, referrers, device breakdown, web vitals (LCP, INP, CLS) if available, and error rate (exceptions or client errors). Help me pin the right insights here.',
    },
    {
        id: 'weekly_marketing_health',
        label: 'Check whether this week is doing better than last week',
        prompt: 'I want a weekly health view for our marketing site: week-over-week visitors, conversion funnel to signup, geo split, and flag for any anomaly vs prior week. Help me build it on this dashboard.',
    },
    {
        id: 'mixed_full_funnel',
        label: 'Follow the journey from traffic to signup to retention and feedback',
        prompt: 'Combine landing page + website metrics into one dashboard covering Acquisition (UTMs, landing pages), Activation (signup funnel), Retention (returning visitors), Research (survey + feedback volume). Using this dashboard, help me build that.',
    },
    {
        id: 'user_research_ops',
        label: 'Hear what people say in surveys and dig into the right sessions',
        prompt: 'Build a user research ops dashboard: survey response volume and completion rate, NPS/CSAT if we use surveys, feature request tags from feedback events, and session replay sampled from users who rated low. Add insights to this dashboard.',
    },
]

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
    const { reportDashboardEmptyAiPromptClicked } = useActions(eventUsageLogic)
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

    const aiSection = (
        <div className="rounded-xl border-2 border-[var(--color-ai)] bg-bg-surface-primary p-4">
            <div className="flex items-center gap-2 mb-1">
                <IconSparkles className="text-ai size-4 shrink-0" />
                <span className="text-sm font-semibold">Try PostHog AI</span>
            </div>
            <p className="text-sm text-secondary m-0 mb-3">
                Pick a topic below. PostHog AI does the work so you can look at the data you care about quickly.
            </p>
            <div className="flex flex-wrap gap-2">
                {DASHBOARD_AI_PROMPT_CHIPS.map((chip) => {
                    const button = (
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="max-w-full whitespace-normal text-left [&_.LemonButton__chrome]:h-auto [&_.LemonButton__chrome]:py-1.5"
                            disabledReason={chipDisabledReason}
                            data-attr={`dashboard-empty-ai-prompt-${chip.id}`}
                            onClick={() => {
                                reportDashboardEmptyAiPromptClicked(chip.label, dashboard?.id)
                                onOpenAiWithPrompt(chip.prompt)
                            }}
                        >
                            {chip.label}
                        </LemonButton>
                    )
                    return (
                        <Tooltip key={chip.id} title={chipDisabledReason ? chipDisabledReason : chip.prompt}>
                            {button}
                        </Tooltip>
                    )
                })}
            </div>
        </div>
    )

    return (
        <div className="flex flex-col gap-5 w-full max-w-full">
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 @min-[48rem]/main-content:justify-start">
                {addInsightButton}
            </div>
            {aiSection}
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
            className="mt-4 mb-2 px-4 @min-[40rem]/main-content:px-8 py-20 @min-[48rem]/main-content:py-28"
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
