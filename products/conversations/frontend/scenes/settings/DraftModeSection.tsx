import { useActions, useValues } from 'kea'

import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'
import { Card, CardContent } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { QuillSettingsSubsection } from '../../components/QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillSettingsSwitchRow } from '../../components/QuillSettingsSwitchRow/QuillSettingsSwitchRow'
import { conversationsDraftModeLogic } from './conversationsDraftModeLogic'

export function DraftModeSection(): JSX.Element {
    const { draftModeDefault } = useValues(conversationsDraftModeLogic)
    const { setDraftModeDefault } = useActions(conversationsDraftModeLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillSettingsSubsection
                title="Draft mode"
                description="Adds a confirmation step before a reply is sent. This is a default applied to each ticket you open. You can still turn it off for a single ticket."
            >
                <Card size="sm" className="max-w-200">
                    <CardContent>
                        <QuillSettingsSwitchRow
                            label="Turn on draft mode by default"
                            description="When on, sending a reply asks you to confirm the recipient first."
                            checked={draftModeDefault}
                            onCheckedChange={setDraftModeDefault}
                        />
                    </CardContent>
                </Card>
            </QuillSettingsSubsection>
        )
    }

    return (
        <SceneSection
            title="Draft mode"
            titleSize="sm"
            className="my-8"
            description="Adds a confirmation step before a reply is sent. This is a default applied to each ticket you open. You can still turn it off for a single ticket."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="font-medium">Turn on draft mode by default</label>
                        <p className="text-xs text-muted-alt mb-0">
                            When on, sending a reply asks you to confirm the recipient first.
                        </p>
                    </div>
                    <LemonSwitch checked={draftModeDefault} onChange={setDraftModeDefault} />
                </div>
            </LemonCard>
        </SceneSection>
    )
}
