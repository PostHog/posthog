import { useActions, useValues } from 'kea'

import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'
import { Card, CardContent } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { businessKnowledgeSettingsLogic } from 'products/business_knowledge/frontend/scenes/settings/businessKnowledgeSettingsLogic'
import { LearnFromPastTicketsSetting } from 'products/business_knowledge/frontend/scenes/settings/LearnFromPastTicketsSetting'

import { QuillSettingsSwitchRow } from '../../components/QuillSettingsSwitchRow/QuillSettingsSwitchRow'

const SWITCH_ID = 'support-ai-learn-from-support-switch'

export function LearnFromSupportCard(): JSX.Element {
    const { settings, settingsLoading, settingsSaving } = useValues(businessKnowledgeSettingsLogic)
    const { setLearnFromSupportEnabled } = useActions(businessKnowledgeSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const disabledReason = !settings
        ? settingsLoading
            ? undefined
            : "Couldn't load this setting. Refresh the page to try again."
        : !settings.support_enabled && !settings.learn_from_support_enabled
          ? 'Turn on Support to learn from resolved tickets'
          : undefined

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <Card size="sm" className="max-w-200">
                    <CardContent>
                        <QuillSettingsSwitchRow
                            id={SWITCH_ID}
                            label="Learn from support"
                            description="Learned answers are added to your Business knowledge sources."
                            checked={!!settings?.learn_from_support_enabled}
                            onCheckedChange={setLearnFromSupportEnabled}
                            loading={settingsLoading || settingsSaving}
                            disabledReason={disabledReason}
                            // data-attr is a frozen autocapture / Playwright key. Do not rename.
                            dataAttr="support-ai-learn-from-support"
                        />
                    </CardContent>
                </Card>
                <LearnFromPastTicketsSetting />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label htmlFor={SWITCH_ID} className="font-medium">
                            Learn from support
                        </label>
                        <p className="text-xs text-muted-alt mb-0">
                            Learned answers are added to your Business knowledge sources.
                        </p>
                    </div>
                    <LemonSwitch
                        id={SWITCH_ID}
                        checked={!!settings?.learn_from_support_enabled}
                        onChange={setLearnFromSupportEnabled}
                        loading={settingsLoading || settingsSaving}
                        disabledReason={disabledReason}
                        // data-attr is a frozen autocapture / Playwright key. Do not rename.
                        data-attr="support-ai-learn-from-support"
                    />
                </div>
            </LemonCard>
            <LearnFromPastTicketsSetting />
        </div>
    )
}
