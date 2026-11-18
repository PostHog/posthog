import { useActions, useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS, supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'

export function AIContextAccountPropertiesSection(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        accountPropertyOptions,
        accountPropertyOptionsLoading,
        aiContextAccountPropertyIds,
        aiContextAccountPropertiesSaving,
    } = useValues(supportSettingsLogic)
    const { setAiContextAccountPropertyIds } = useActions(supportSettingsLogic)

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]) {
        return null
    }

    return (
        <SceneSection
            title="Account properties in AI context"
            titleSize="sm"
            className="my-8"
            description="The AI includes these Customer analytics account properties when it drafts a reply."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <LemonInputSelect
                    mode="multiple"
                    value={aiContextAccountPropertyIds}
                    onChange={setAiContextAccountPropertyIds}
                    options={accountPropertyOptions.map((option) => ({ key: option.id, label: option.name }))}
                    loading={accountPropertyOptionsLoading}
                    placeholder={`Select up to ${MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS} properties`}
                    limit={MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS}
                    disabledReason={aiContextAccountPropertiesSaving ? 'Saving selected properties' : undefined}
                    emptyStateComponent={<span>No account properties yet. Add them in Customer analytics first.</span>}
                    fullWidth
                    data-attr="ai-context-account-properties"
                />
            </LemonCard>
        </SceneSection>
    )
}
