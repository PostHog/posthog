import { IconPlus } from '@posthog/icons'
import { LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { EmailSender, SenderDataAttrPrefix, fromWithSenders, selectedSenderIds } from './emailSenderFields'
import type { SandboxSenderChoice } from './SandboxSenderChoiceContext'
import {
    SANDBOX_SENDER_VALUE,
    sandboxSenderGroups,
    sandboxSenderInputOptions,
    selectedSenderValue,
} from './sandboxSenderOptions'
import { EmailTemplateFrom, MAX_WORKFLOW_EMAIL_SENDERS } from './types'

const ADD_SENDER = -1

function senderLabel(sender: EmailSender): string {
    const { name, email } = sender.config ?? {}
    return name && email ? `${name} <${email}>` : (email ?? sender.display_name ?? `Sender ${sender.id}`)
}

/** Picks the sender, or several senders when the email rotates between them. */
export function EmailSenderPicker({
    from,
    senders,
    allowRotation = false,
    dataAttrPrefix,
    sandbox = null,
    onChooseSandbox,
    onChangeFrom,
    onAddSender,
}: {
    from: EmailTemplateFrom
    senders: EmailSender[]
    /** Lets a workflow pick several senders, and each run sends from one of them. */
    allowRotation?: boolean
    dataAttrPrefix: SenderDataAttrPrefix
    /** Offers the sandbox sender beside the project's own senders, in workflow email steps. */
    sandbox?: SandboxSenderChoice | null
    onChooseSandbox?: () => void
    onChangeFrom: (from: EmailTemplateFrom) => void
    onAddSender: () => void
}): JSX.Element {
    const changeSenders = (integrationIds: number[]): void => {
        if (integrationIds.includes(SANDBOX_SENDER_VALUE)) {
            onChooseSandbox?.()
            return
        }
        if (integrationIds.length > MAX_WORKFLOW_EMAIL_SENDERS) {
            return
        }
        onChangeFrom(fromWithSenders(from, integrationIds, senders))
    }

    return allowRotation && !sandbox?.selected ? (
        <LemonInputSelect<number>
            mode="multiple"
            placeholder="Choose email senders"
            options={[
                ...senders.map((candidate) => ({
                    key: String(candidate.id),
                    label: senderLabel(candidate),
                    value: candidate.id,
                })),
                ...sandboxSenderInputOptions(sandbox),
            ]}
            value={selectedSenderIds(from)}
            onChange={changeSenders}
            fullWidth
            autoWidth={false}
            action={{
                children: 'Add new email sender',
                icon: <IconPlus />,
                onClick: onAddSender,
                closesDropdown: true,
            }}
            data-attr={`${dataAttrPrefix}-sender-select`}
        />
    ) : (
        <LemonSelect
            fullWidth
            size="small"
            placeholder="Choose an email sender"
            value={selectedSenderValue(sandbox, from.integrationId)}
            onChange={(id) => (id === ADD_SENDER ? onAddSender() : changeSenders([id]))}
            options={[
                { options: senders.map((candidate) => ({ value: candidate.id, label: senderLabel(candidate) })) },
                ...sandboxSenderGroups(sandbox),
                { options: [{ value: ADD_SENDER, label: 'Add new email sender', icon: <IconPlus /> }] },
            ]}
            data-attr={`${dataAttrPrefix}-sender-select`}
        />
    )
}
