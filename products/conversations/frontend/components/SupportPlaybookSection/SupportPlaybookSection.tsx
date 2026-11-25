import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { SupportPlaybookEditor } from '../SupportPlaybookEditor/SupportPlaybookEditor'

export function SupportPlaybookSection(): JSX.Element {
    const {
        playbook,
        playbookLoading,
        playbookDraft,
        playbookSaving,
        playbookError,
        playbookDirty,
        aiReplyCustomized,
    } = useValues(supportSettingsLogic)
    const { setPlaybookDraft, savePlaybook, resetPlaybook } = useActions(supportSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const editor = (
        <SupportPlaybookEditor
            inheritedInstructions={playbook?.inherited_instructions ?? ''}
            draft={playbookDraft}
            isCustomized={aiReplyCustomized}
            maxChars={playbook?.max_chars ?? 8000}
            saving={playbookSaving}
            loading={playbookLoading}
            error={playbookError}
            dirty={playbookDirty}
            onDraftChange={setPlaybookDraft}
            onSave={savePlaybook}
            onReset={resetPlaybook}
        />
    )

    if (todayRailNav) {
        return (
            <QuillSettingsSubsection
                title="Support playbook"
                description="Add extra instructions on top of the default playbook. Safety rules and available tools stay the same."
            >
                {editor}
            </QuillSettingsSubsection>
        )
    }

    return (
        <SceneSection
            title="Support playbook"
            titleSize="sm"
            className="my-8"
            description="Add extra instructions on top of the default playbook. Safety rules and available tools stay the same."
        >
            {editor}
        </SceneSection>
    )
}
