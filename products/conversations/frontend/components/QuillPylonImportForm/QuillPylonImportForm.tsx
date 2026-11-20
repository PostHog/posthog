import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldDescription, FieldLabel, Input, Text } from '@posthog/quill'

import { pylonImportLogic } from '../../scenes/settings/pylonImportLogic'
import { QuillImportInboxField } from '../QuillImportInboxField/QuillImportInboxField'
import { QuillImportSection } from '../QuillImportSection/QuillImportSection'

const IMPORT_RUNNING_REASON = 'Import already running'

export function QuillPylonImportForm({
    startDisabledReason,
}: {
    startDisabledReason: string | null | undefined
}): JSX.Element {
    const {
        apiToken,
        emailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(pylonImportLogic)
    const { setApiToken, setEmailChannelId, submitImport } = useActions(pylonImportLogic)
    const id = useId()
    const inputDisabledReason = isImportRunning ? IMPORT_RUNNING_REASON : undefined

    return (
        <QuillImportSection
            title="Pylon import"
            description="Import historical Pylon issues and their message threads into Support as tickets. Issues you already imported are skipped when you run it again. Pylon limits how fast issues can be read, so a large workspace can take several hours."
            status={importJob?.status}
            progressLabel={importProgressLabel}
            latestError={importJob?.latest_error}
            completedSummary={
                importJob ? (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Imported {importJob.imported_issues.toLocaleString()} issues (
                        {importJob.skipped_issues.toLocaleString()} skipped, {importJob.failed_issues.toLocaleString()}{' '}
                        failed).
                    </Text>
                ) : null
            }
            warning={
                emailChannelId === null && !isImportRunning
                    ? "Without a reply inbox, imported tickets have no email channel. Agents can read them but can't reply to those customers by email."
                    : null
            }
            onStartImport={submitImport}
            startLoading={importJobLoading}
            startDisabledReason={startDisabledReason}
        >
            <Field>
                <FieldLabel htmlFor={`${id}-token`}>API token</FieldLabel>
                <Input
                    id={`${id}-token`}
                    type="password"
                    placeholder={
                        importJob?.has_credentials
                            ? 'Configured. Enter it again to start a new import.'
                            : 'Pylon API token'
                    }
                    value={apiToken}
                    onChange={(event) => setApiToken(event.target.value)}
                    disabledReason={inputDisabledReason}
                />
                <FieldDescription>
                    A Pylon admin can create one under Settings &gt; Integrations &amp; dev &gt; API tokens. The token's
                    role must be able to read issues, messages, and contacts. US and EU workspaces both work, and the
                    region is detected from the token.
                </FieldDescription>
            </Field>
            <QuillImportInboxField
                label="Reply inbox"
                description="Imported tickets are attached to this support inbox so agents can reply to customers by email. An issue sent to another support address that is connected here keeps that inbox."
                noneLabel="No inbox"
                placeholder="No inbox"
                emailConfigs={emailConfigs}
                value={emailChannelId}
                onChange={setEmailChannelId}
                disabledReason={inputDisabledReason}
            />
        </QuillImportSection>
    )
}
