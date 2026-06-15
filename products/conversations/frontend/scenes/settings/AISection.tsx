import { useActions, useValues } from 'kea'

import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function AISection(): JSX.Element {
    const { aiSuggestionsEnabled, aiSuggestionsLoading } = useValues(supportSettingsLogic)
    const { setAiSuggestionsEnabled } = useActions(supportSettingsLogic)

    return (
        <SceneSection
            title="AI suggestions"
            className="my-8"
            description="When enabled, PostHog will automatically generate a suggested reply as a private note whenever a new ticket arrives. Suggestions are grounded in your business knowledge sources."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="font-medium">Allow AI suggestions</label>
                        <p className="text-xs text-muted-alt mb-0">
                            Requires AI data processing consent at the organization level and at least one ready
                            business knowledge source.
                        </p>
                    </div>
                    <LemonSwitch
                        checked={aiSuggestionsEnabled}
                        onChange={(checked) => setAiSuggestionsEnabled(checked)}
                        loading={aiSuggestionsLoading}
                    />
                </div>
            </LemonCard>
        </SceneSection>
    )
}
