import { useActions, useValues } from 'kea'

import { IconBug, IconQuestion } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SupportTicketKind, SupportTicketTargetArea, supportLogic } from 'lib/components/Support/supportLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

interface SupportModalButtonProps {
    name?: string
    email?: string
    kind?: SupportTicketKind
    target_area?: SupportTicketTargetArea
    label?: string
}

export function SupportModalButton({
    name,
    email,
    kind = 'bug',
    target_area = 'login',
    label = 'Report an issue',
}: SupportModalButtonProps): JSX.Element | null {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    return preflight?.cloud ? ( // We don't provide support for self-hosted instances
        <>
            <div className="text-center">
                <LemonButton
                    onClick={() => {
                        openSupportForm({
                            name,
                            email,
                            kind,
                            target_area,
                        })
                    }}
                    icon={kind === 'bug' ? <IconBug /> : <IconQuestion />}
                    size="small"
                >
                    <span className="text-secondary">{label}</span>
                </LemonButton>
            </div>
        </>
    ) : null
}
