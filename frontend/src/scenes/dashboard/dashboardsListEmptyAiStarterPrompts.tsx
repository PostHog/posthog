import { DashboardAiPromptChip, DashboardAiPromptChips } from './dashboardAiPromptChips'

/** Prompts when the project has no dashboards yet: AI helps plan a first board (not “this dashboard”). */
export const DASHBOARDS_LIST_EMPTY_AI_PROMPT_CHIPS: readonly DashboardAiPromptChip[] = [
    {
        id: 'first_board_pages_and_sources',
        label: 'See which pages get the most traffic and where people come from',
        prompt: "I don't have a dashboard yet. Help me plan a first one around traffic: which pages or routes are getting the most views, and where visitors are coming from (referrer, UTM, or channel when available). Assume I have pageviews or $pageview. Suggest insight types and a sensible order to build them.",
    },
    {
        id: 'first_board_usage_trend',
        label: 'See whether usage is going up, flat, or down over time',
        prompt: "I don't have a dashboard yet. Help me plan a first board that answers whether more people are showing up over time: what to plot (DAU, weekly active users, or a key event), good default time ranges, and one breakdown that usually helps. Suggest a dashboard name and a short list of insights in order.",
    },
    {
        id: 'first_board_new_posthog_one_journey',
        label: 'Plan a dashboard around one user journey you care about',
        prompt: "I don't have a dashboard yet. Help me plan a first dashboard centered on one journey that matters (for example visit to signup, or signup to first meaningful action). Suggest several complementary insights: at minimum a funnel across the steps, plus a few supporting charts (for example volume or conversion over time, a useful breakdown, or drop-off focus on the worst step). Walk me through events or pageviews to use, a dashboard name, and the insights in a sensible build order.",
    },
]

export type DashboardsListEmptyAiStarterPromptsProps = {
    chipDisabledReason?: string | null
    onOpenAiWithPrompt: (prompt: string) => void
    className?: string
}

export function DashboardsListEmptyAiStarterPrompts({
    chipDisabledReason,
    onOpenAiWithPrompt,
    className,
}: DashboardsListEmptyAiStarterPromptsProps): JSX.Element {
    return (
        <DashboardAiPromptChips
            chips={DASHBOARDS_LIST_EMPTY_AI_PROMPT_CHIPS}
            chipDisabledReason={chipDisabledReason}
            onOpenAiWithPrompt={onOpenAiWithPrompt}
            dataAttrPrefix="dashboards-list-empty-ai-prompt"
            className={className}
            description="No dashboard yet? Pick a topic and PostHog AI can help you plan what to build first."
        />
    )
}
