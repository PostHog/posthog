import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { wizardSyncUiLogic } from './wizardSyncUiLogic'

/**
 * The handoff doc dialog: renders the markdown report a wizard run produced. Mounted once app-wide
 * (next to the FAB) rather than per surface, so the one-time auto-open works no matter which scene
 * the user is on; the run surfaces reopen it through `openHandoffDoc`.
 */
export function WizardHandoffDialog(): JSX.Element {
    const { handoffDoc } = useValues(wizardSyncUiLogic)
    const { closeHandoffDoc } = useActions(wizardSyncUiLogic)
    return (
        <LemonModal
            isOpen={!!handoffDoc}
            onClose={closeHandoffDoc}
            title="Setup report"
            description="The agent wrote this report about the run it just finished."
            width={640}
        >
            {/* ph-no-capture: the report describes the customer's codebase (file paths, event
                names, framework detail) and must not reach autocapture. disableImages: the text is
                agent output, so an inline image would fire a request to an arbitrary URL. */}
            <div className="ph-no-capture" data-attr="wizard-handoff-doc">
                <LemonMarkdown disableImages>{handoffDoc?.text ?? ''}</LemonMarkdown>
            </div>
        </LemonModal>
    )
}
