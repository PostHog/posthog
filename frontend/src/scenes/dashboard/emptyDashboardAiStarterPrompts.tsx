import { DashboardAiPromptChip, DashboardAiPromptChips } from './dashboardAiPromptChips'

export const EMPTY_DASHBOARD_AI_PROMPT_CHIPS: readonly DashboardAiPromptChip[] = [
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

export type EmptyDashboardAiStarterPromptsProps = {
    dashboardId?: number
    chipDisabledReason?: string | null
    onOpenAiWithPrompt: (prompt: string) => void
    className?: string
}

export function EmptyDashboardAiStarterPrompts({
    dashboardId,
    chipDisabledReason,
    onOpenAiWithPrompt,
    className,
}: EmptyDashboardAiStarterPromptsProps): JSX.Element {
    return (
        <DashboardAiPromptChips
            chips={EMPTY_DASHBOARD_AI_PROMPT_CHIPS}
            dashboardId={dashboardId}
            chipDisabledReason={chipDisabledReason}
            onOpenAiWithPrompt={onOpenAiWithPrompt}
            dataAttrPrefix="dashboard-empty-ai-prompt"
            className={className}
            maxChips={3}
        />
    )
}
