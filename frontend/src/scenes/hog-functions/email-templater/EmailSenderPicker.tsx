import { IconExternal } from '@posthog/icons'
import { LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import {
    EmailSender,
    SenderDataAttrPrefix,
    addressFromLocalPart,
    addressLocalPart,
    selectedSenderIds,
    selectedSenders,
    sharedSenderDomain,
} from './emailSenderFields'
import { EmailTemplateFrom, MAX_WORKFLOW_EMAIL_SENDERS } from './types'

const ADD_SENDER = -1

function senderLabel(sender: EmailSender): string {
    const { name, email } = sender.config ?? {}
    return name && email ? `${name} <${email}>` : (email ?? sender.display_name ?? `Sender ${sender.id}`)
}

function openSenderSetup(): void {
    window.open(urls.workflows('channels'), '_blank')
}

/** Picks the sender, or several senders when the email rotates between them. */
export function EmailSenderPicker({
    from,
    senders,
    allowRotation = false,
    dataAttrPrefix,
    onChangeFrom,
}: {
    from: EmailTemplateFrom
    senders: EmailSender[]
    /** Lets a workflow pick several senders, and each run sends from one of them. */
    allowRotation?: boolean
    dataAttrPrefix: SenderDataAttrPrefix
    onChangeFrom: (from: EmailTemplateFrom) => void
}): JSX.Element {
    const changeSenders = (integrationIds: number[]): void => {
        // A custom address keeps its part before the @ and moves to the new senders' domain.
        const domain = sharedSenderDomain(selectedSenders(from, senders))
        const nextDomain = sharedSenderDomain(senders.filter((candidate) => integrationIds.includes(candidate.id)))
        const email = from.email ? addressFromLocalPart(addressLocalPart(from.email, domain), nextDomain) : undefined
        onChangeFrom({
            ...from,
            integrationId: integrationIds[0],
            integrationIds: integrationIds.length > 1 ? integrationIds : undefined,
            email,
        })
    }

    return allowRotation ? (
        <LemonInputSelect<number>
            mode="multiple"
            placeholder="Choose email senders"
            options={senders.map((candidate) => ({
                key: String(candidate.id),
                label: senderLabel(candidate),
                value: candidate.id,
            }))}
            value={selectedSenderIds(from)}
            onChange={(ids) => ids.length <= MAX_WORKFLOW_EMAIL_SENDERS && changeSenders(ids)}
            fullWidth
            autoWidth={false}
            action={{ children: 'Add new email sender', icon: <IconExternal />, onClick: openSenderSetup }}
            data-attr={`${dataAttrPrefix}-sender-select`}
        />
    ) : (
        <LemonSelect
            fullWidth
            size="small"
            placeholder="Choose an email sender"
            value={from.integrationId}
            onChange={(id) => (id === ADD_SENDER ? openSenderSetup() : changeSenders([id]))}
            options={[
                { options: senders.map((candidate) => ({ value: candidate.id, label: senderLabel(candidate) })) },
                { options: [{ value: ADD_SENDER, label: 'Add new email sender', icon: <IconExternal /> }] },
            ]}
            data-attr={`${dataAttrPrefix}-sender-select`}
        />
    )
}
