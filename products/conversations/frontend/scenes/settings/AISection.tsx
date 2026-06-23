import { useActions, useValues } from 'kea'

import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function AISection(): JSX.Element {
    const { aiSuggestionsEnabled, aiSuggestionsLoading, aiDiagnosticsEnabled, aiDiagnosticsLoading } =
        useValues(supportSettingsLogic)
    const { setAiSuggestionsEnabled, setAiDiagnosticsEnabled } = useActions(supportSettingsLogic)

    return (
        <SceneSection
            title="AI suggestions"
            className="my-8"
            description="When enabled, PostHog will automatically generate a suggested reply as a private note whenever a new ticket arrives. Suggestions are grounded in your business knowledge sources."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <LemonSwitch
                    checked={aiSuggestionsEnabled}
                    onChange={(checked) => setAiSuggestionsEnabled(checked)}
                    loading={aiSuggestionsLoading}
                    label="Allow AI suggestions"
                />
                <p className="text-xs text-muted-alt mb-0">
                    Requires AI data processing consent at the organization level and at least one ready business
                    knowledge source.
                </p>
            </LemonCard>
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <LemonSwitch
                    checked={aiDiagnosticsEnabled}
                    onChange={(checked) => setAiDiagnosticsEnabled(checked)}
                    loading={aiDiagnosticsLoading}
                    disabledReason={!aiSuggestionsEnabled ? 'Enable AI suggestions first' : undefined}
                    label="Allow the agent to investigate ticket data"
                />
                <p className="text-xs text-muted-alt mb-0">
                    When enabled, tickets that report something broken let the agent query your project's data — events,
                    error tracking, session recordings, and logs — to investigate the issue instead of relying on
                    documentation alone. The agent has read-only access scoped to your project. Leave this off to keep
                    suggestions grounded only in documentation and your business knowledge.
                </p>
            </LemonCard>
        </SceneSection>
    )
}
