import { useActions, useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS, supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillAIContextAccountPropertiesPicker } from './QuillAIContextAccountPropertiesPicker'

export function AIContextAccountPropertiesSection(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        accountPropertyOptions,
        accountPropertyOptionsLoading,
        aiContextAccountPropertyIds,
        aiContextAccountPropertiesSaving,
    } = useValues(supportSettingsLogic)
    const { setAiContextAccountPropertyIds } = useActions(supportSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]) {
        return null
    }

    const options = accountPropertyOptions.map((option) => ({ key: option.id, label: option.name }))
    const placeholder = `Select up to ${MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS} properties`
    const disabledReason = aiContextAccountPropertiesSaving ? 'Saving selected properties' : undefined

    if (todayRailNav) {
        return (
            <QuillSettingsSubsection
                title="Account properties in AI context"
                description="The AI includes these Customer analytics account properties when it drafts a reply."
            >
                <QuillAIContextAccountPropertiesPicker
                    options={options}
                    loading={accountPropertyOptionsLoading}
                    value={aiContextAccountPropertyIds}
                    limit={MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS}
                    placeholder={placeholder}
                    disabledReason={disabledReason}
                    onChange={setAiContextAccountPropertyIds}
                />
            </QuillSettingsSubsection>
        )
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
                    options={options}
                    loading={accountPropertyOptionsLoading}
                    placeholder={placeholder}
                    limit={MAX_AI_CONTEXT_ACCOUNT_PROPERTY_IDS}
                    disabledReason={disabledReason}
                    emptyStateComponent={<span>No account properties yet. Add them in Customer analytics first.</span>}
                    fullWidth
                    data-attr="ai-context-account-properties"
                />
            </LemonCard>
        </SceneSection>
    )
}
