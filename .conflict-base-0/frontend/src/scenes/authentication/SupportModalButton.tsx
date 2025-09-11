import { useActions, useValues } from 'kea'

import { IconBug } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
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
                    icon={<IconBug />}
                    size="small"
                >
                    <span className="text-secondary">Report an issue</span>
                </LemonButton>
            </div>
        </>
    ) : null
}
