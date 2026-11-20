import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { agentInstructionsSettingsLogic } from './agentInstructionsSettingsLogic'
import { InstructionsEditor } from './InstructionsEditor'
import { QuillInstructionsEditor } from './QuillInstructionsEditor'

export function AgentPersonalInstructionsSettings(): JSX.Element {
    const { personalInstructions, personalValue, personalDirty, personalInstructionsLoading } =
        useValues(agentInstructionsSettingsLogic)
    const { setPersonalDraft, submitPersonalDraft } = useActions(agentInstructionsSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const Editor = todayRailNav ? QuillInstructionsEditor : InstructionsEditor

    return (
        <Editor
            stored={personalInstructions}
            value={personalValue}
            dirty={personalDirty}
            loading={personalInstructionsLoading}
            placeholder="For example: Keep pull request descriptions short. Ask before adding a dependency."
            onChange={setPersonalDraft}
            onSave={submitPersonalDraft}
            dataAttr="agent-personal-instructions"
            ariaLabel="My instructions"
        />
    )
}
