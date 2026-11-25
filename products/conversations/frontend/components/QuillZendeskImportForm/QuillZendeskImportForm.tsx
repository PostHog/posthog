import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldLabel, Input, Text } from '@posthog/quill'

import { zendeskImportLogic } from '../../scenes/settings/zendeskImportLogic'
import { QuillImportInboxField } from '../QuillImportInboxField/QuillImportInboxField'
import { QuillImportSection } from '../QuillImportSection/QuillImportSection'

const IMPORT_RUNNING_REASON = 'Import already running'

export function QuillZendeskImportForm({
    startDisabledReason,
}: {
    startDisabledReason: string | null | undefined
}): JSX.Element {
    const {
        subdomain,
        emailAddress,
        apiToken,
        defaultEmailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(zendeskImportLogic)
    const { setSubdomain, setEmailAddress, setApiToken, setDefaultEmailChannelId, submitImport } =
        useActions(zendeskImportLogic)
    const id = useId()
    const inputDisabledReason = isImportRunning ? IMPORT_RUNNING_REASON : undefined

    return (
        <QuillImportSection
            title="Zendesk import"
            description="Import historical Zendesk Support tickets and message threads into Support. Already-synced tickets are skipped on re-run."
            status={importJob?.status}
            progressLabel={importProgressLabel}
            latestError={importJob?.latest_error}
            completedSummary={
                importJob ? (
                    <>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Imported {importJob.imported_tickets.toLocaleString()} tickets (
                            {importJob.skipped_tickets.toLocaleString()} skipped,{' '}
                            {importJob.failed_tickets.toLocaleString()} failed).
                        </Text>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            If the imported total is lower than the latest ticket number in Zendesk, that is usually
                            expected. Ticket numbers count every ticket ever created, including gaps from deleted
                            tickets. The export API only returns tickets Zendesk still exposes: permanently deleted
                            tickets (after retention), archived tickets, and AI agent tickets may be omitted.
                        </Text>
                    </>
                ) : null
            }
            warning={
                defaultEmailChannelId === null && !isImportRunning
                    ? "Without a default inbox, tickets whose Zendesk address doesn't match one of your connected support addresses are imported without an email channel. Agents won't be able to reply to those customers by email, and the reply box on those tickets will be disabled."
                    : null
            }
            onStartImport={submitImport}
            startLoading={importJobLoading}
            startDisabledReason={startDisabledReason}
        >
            <Field>
                <FieldLabel htmlFor={`${id}-subdomain`}>Zendesk subdomain</FieldLabel>
                <Input
                    id={`${id}-subdomain`}
                    type="text"
                    placeholder="Zendesk subdomain"
                    value={subdomain}
                    onChange={(event) => setSubdomain(event.target.value)}
                    disabledReason={inputDisabledReason}
                />
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-email`}>Zendesk agent email</FieldLabel>
                <Input
                    id={`${id}-email`}
                    type="email"
                    placeholder={
                        importJob?.has_credentials
                            ? 'Zendesk agent email (configured — re-enter to start a new import)'
                            : 'Zendesk agent email'
                    }
                    value={emailAddress}
                    onChange={(event) => setEmailAddress(event.target.value)}
                    disabledReason={inputDisabledReason}
                />
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-token`}>Zendesk API token</FieldLabel>
                <Input
                    id={`${id}-token`}
                    type="password"
                    placeholder={
                        importJob?.has_credentials
                            ? 'Zendesk API token (configured — re-enter to start a new import)'
                            : 'Zendesk API token'
                    }
                    value={apiToken}
                    onChange={(event) => setApiToken(event.target.value)}
                    disabledReason={inputDisabledReason}
                />
            </Field>
            <QuillImportInboxField
                label="Default inbox"
                description="Fallback email channel for tickets whose original Zendesk recipient doesn't match one of your configured support addresses (e.g. a *.zendesk.com address, or a non-email ticket). Tickets that do match are assigned to the matching channel regardless of this setting."
                noneLabel="No default"
                placeholder="No default (leave unmatched tickets without an inbox)"
                emailConfigs={emailConfigs}
                value={defaultEmailChannelId}
                onChange={setDefaultEmailChannelId}
                disabledReason={inputDisabledReason}
            />
        </QuillImportSection>
    )
}
