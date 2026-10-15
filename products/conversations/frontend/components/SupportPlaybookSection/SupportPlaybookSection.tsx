import { useActions, useValues } from 'kea'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
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

    return (
        <SceneSection
            title="Support playbook"
            titleSize="sm"
            className="my-8"
            description="Add extra instructions on top of the default playbook. Safety rules and available tools stay the same."
        >
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
        </SceneSection>
    )
}
