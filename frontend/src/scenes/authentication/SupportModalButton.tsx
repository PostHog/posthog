import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { SupportModal } from 'lib/components/Support/SupportModal'
import { IconBugShield } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export function SupportModalButton({ name, email }: { name?: string; email?: string }): JSX.Element | null {
    const { openSupportLoggedOutForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    return preflight?.cloud ? ( // We don't provide support for self-hosted instances
        <>
            <div className="text-center">
                <LemonButton
                    onClick={() => {
                        openSupportLoggedOutForm(name, email, null, 'login')
                    }}
                    status="stealth"
                    icon={<IconBugShield />}
                    size="small"
                >
                    <span className="text-muted">Report an issue</span>
                </LemonButton>
            </div>
            <SupportModal loggedIn={false} />
        </>
    ) : null
}
