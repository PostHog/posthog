import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { terminalLogic } from './terminalLogic'

export function TerminalConfirmationModal(): JSX.Element | null {
    const { confirmation } = useValues(terminalLogic)
    const { answerConfirmation } = useActions(terminalLogic)
    if (!confirmation) {
        return null
    }
    return (
        <LemonModal
            width={640}
            overlayClassName="!items-center !bg-black/70"
            closable={false}
            forceAbovePopovers
            title={confirmation.title}
            className="ph-no-capture ph-replay-block"
            data-attr="terminal-confirmation"
            footer={
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        data-attr="terminal-confirmation-cancel"
                        onClick={(event) => {
                            if (event.detail === 1) {
                                answerConfirmation(confirmation, false)
                            }
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        data-attr="terminal-confirmation-approve"
                        onClick={(event) => {
                            if (event.detail === 1) {
                                answerConfirmation(confirmation, true)
                            }
                        }}
                    >
                        Yes, continue
                    </LemonButton>
                </div>
            }
        >
            <p>{confirmation.description}</p>
            <p>The terminal is waiting. Click a button to continue or cancel. Keyboard shortcuts are disabled.</p>
            <ul className="space-y-2 pl-4" translate="no">
                {confirmation.items.map((item, index) => (
                    <li key={index} className="whitespace-pre-wrap break-words font-mono text-sm">
                        {item}
                    </li>
                ))}
            </ul>
        </LemonModal>
    )
}
