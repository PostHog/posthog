import { useActions, useValues } from 'kea'

import { IconExternal, IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import { EmailHeaderRow } from './EmailHeaderRow'
import { EmailSender, isSendingStopped, sendingStoppedWarning } from './emailSenderFields'
import { SandboxSenderChoice } from './SandboxSenderChoiceContext'
import { sandboxSenderHint } from './sandboxSenderOptions'

export function TestSenderRow({
    sandbox,
    senders,
}: {
    sandbox: SandboxSenderChoice
    senders: EmailSender[]
}): JSX.Element {
    const unverified = senders
        .filter((sender) => sender.config?.verified !== true && !isSendingStopped(sender))
        .map((sender) => sender.config?.email ?? sender.display_name ?? `Sender ${sender.id}`)
    const stopped = sendingStoppedWarning(senders)
    const { integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrationsOfKind } = useActions(integrationsLogic)
    return (
        <EmailHeaderRow label="From" className="py-1">
            <div className="flex-1 min-w-0" data-attr="workflow-email-test-sender">
                <div className="truncate">PostHog test sender</div>
                <div className="flex flex-wrap gap-x-3 mt-0.5 text-xs text-secondary">
                    <span className="min-w-0 truncate">{sandboxSenderHint(sandbox)}</span>
                    {unverified.length > 0 ? (
                        <span className="min-w-0 break-words text-warning">
                            {`${unverified.join(', ')} ${unverified.length === 1 ? "isn't" : "aren't"} verified yet.`}
                        </span>
                    ) : null}
                    {stopped ? <span className="min-w-0 break-words text-warning">{stopped}</span> : null}
                </div>
            </div>
            <LemonButton
                size="xsmall"
                type="tertiary"
                className="shrink-0"
                icon={<IconRefresh />}
                loading={integrationsLoading}
                onClick={() => loadIntegrationsOfKind('email')}
                data-attr="workflow-email-test-sender-refresh"
            >
                Check again
            </LemonButton>
            <LemonButton
                size="xsmall"
                type="secondary"
                className="shrink-0"
                to={urls.workflows('channels')}
                targetBlank
                icon={<IconExternal />}
                data-attr="workflow-email-test-sender-add"
            >
                Add new email sender
            </LemonButton>
        </EmailHeaderRow>
    )
}
