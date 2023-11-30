import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconBugShield } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export function SupportModalButton({ name, email }: { name?: string; email?: string }): JSX.Element | null {
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
                            kind: 'bug',
                            target_area: 'login',
                        })
                    }}
                    status="stealth"
                    icon={<IconBugShield />}
                    size="small"
                >
                    <span className="text-muted">Report an issue</span>
                </LemonButton>
            </div>
        </>
    ) : null
}
