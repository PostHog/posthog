import { IconInfo } from '@posthog/icons'
import { LemonButton, Tooltip, type LemonSelectSection } from '@posthog/lemon-ui'

import type { LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import type { SandboxSenderChoice } from './SandboxSenderChoiceContext'

export const SANDBOX_SENDER_VALUE = -2
const SANDBOX_SENDER_LABEL = 'Sandbox sender'
const SANDBOX_RECIPIENTS_NOTE = 'Only verified members of your organization receive sandbox email.'

export function sandboxSenderGroups(sandbox: SandboxSenderChoice | null): LemonSelectSection<number>[] {
    if (!sandbox) {
        return []
    }
    return [
        {
            title: 'PostHog',
            options: [
                {
                    label: SANDBOX_SENDER_LABEL,
                    value: SANDBOX_SENDER_VALUE,
                    labelInMenu: (
                        <div className="flex flex-col py-1">
                            <span>{SANDBOX_SENDER_LABEL}</span>
                            <span className="text-xs text-secondary">
                                Works before you verify a domain. Delivers only to verified members of your
                                organization.
                            </span>
                        </div>
                    ),
                },
            ],
        },
    ]
}

export function sandboxSenderInputOptions(sandbox: SandboxSenderChoice | null): LemonInputSelectOption<number>[] {
    return sandbox
        ? [{ key: String(SANDBOX_SENDER_VALUE), label: SANDBOX_SENDER_LABEL, value: SANDBOX_SENDER_VALUE }]
        : []
}

export function selectedSenderValue(
    sandbox: SandboxSenderChoice | null,
    integrationId: number | undefined
): number | undefined {
    return sandbox?.selected ? SANDBOX_SENDER_VALUE : integrationId
}

export function sandboxSenderHint(sandbox: SandboxSenderChoice | null): JSX.Element | null {
    if (!sandbox?.selected) {
        return null
    }
    if (!sandbox.fromLine) {
        return <span>{SANDBOX_RECIPIENTS_NOTE}</span>
    }
    return (
        <span className="flex gap-1 items-center min-w-0">
            <span className="truncate">{`Sends as ${sandbox.fromLine}.`}</span>
            <Tooltip title={SANDBOX_RECIPIENTS_NOTE}>
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconInfo className="text-secondary" />}
                    aria-label="About sandbox email recipients"
                    data-attr="workflow-email-sandbox-recipients-help"
                    className="shrink-0"
                />
            </Tooltip>
        </span>
    )
}
