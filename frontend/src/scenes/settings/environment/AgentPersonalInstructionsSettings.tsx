import { useActions, useValues } from 'kea'

import { agentInstructionsSettingsLogic } from './agentInstructionsSettingsLogic'
import { InstructionsEditor } from './InstructionsEditor'

export function AgentPersonalInstructionsSettings(): JSX.Element {
    const { personalInstructions, personalValue, personalDirty, personalInstructionsLoading } =
        useValues(agentInstructionsSettingsLogic)
    const { setPersonalDraft, submitPersonalDraft } = useActions(agentInstructionsSettingsLogic)

    return (
        <InstructionsEditor
            stored={personalInstructions}
            value={personalValue}
            dirty={personalDirty}
            loading={personalInstructionsLoading}
            placeholder="For example: Keep pull request descriptions short. Ask before adding a dependency."
            onChange={setPersonalDraft}
            onSave={submitPersonalDraft}
            dataAttr="agent-personal-instructions"
        />
    )
}
