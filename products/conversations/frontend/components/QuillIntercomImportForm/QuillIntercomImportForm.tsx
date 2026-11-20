import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { intercomImportLogic, IntercomRegion } from '../../scenes/settings/intercomImportLogic'
import { QuillImportInboxField } from '../QuillImportInboxField/QuillImportInboxField'
import { QuillImportSection } from '../QuillImportSection/QuillImportSection'

const IMPORT_RUNNING_REASON = 'Import already running'

export function QuillIntercomImportForm({
    regionOptions,
    startDisabledReason,
}: {
    regionOptions: { label: string; value: IntercomRegion }[]
    startDisabledReason: string | null | undefined
}): JSX.Element {
    const {
        region,
        accessToken,
        emailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(intercomImportLogic)
    const { setRegion, setAccessToken, setEmailChannelId, submitImport } = useActions(intercomImportLogic)
    const id = useId()
    const inputDisabledReason = isImportRunning ? IMPORT_RUNNING_REASON : undefined

    return (
        <QuillImportSection
            title="Intercom import"
            description="Import historical Intercom conversations and their message threads into Support as tickets. Conversations you already imported are skipped when you run it again."
            status={importJob?.status}
            progressLabel={importProgressLabel}
            latestError={importJob?.latest_error}
            completedSummary={
                importJob ? (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Imported {importJob.imported_conversations.toLocaleString()} conversations (
                        {importJob.skipped_conversations.toLocaleString()} skipped,{' '}
                        {importJob.failed_conversations.toLocaleString()} failed).
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
                <FieldLabel htmlFor={`${id}-region`}>Workspace region</FieldLabel>
                <Select<IntercomRegion>
                    items={regionOptions}
                    value={region}
                    onValueChange={(next) => next && setRegion(next)}
                >
                    <SelectTrigger id={`${id}-region`} className="w-full" disabledReason={inputDisabledReason}>
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {regionOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <FieldDescription>Where your Intercom workspace is hosted.</FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-token`}>Access token</FieldLabel>
                <Input
                    id={`${id}-token`}
                    type="password"
                    placeholder={
                        importJob?.has_credentials
                            ? 'Configured. Enter it again to start a new import.'
                            : 'Intercom access token'
                    }
                    value={accessToken}
                    onChange={(event) => setAccessToken(event.target.value)}
                    disabledReason={inputDisabledReason}
                />
                <FieldDescription>
                    Create an app in Intercom's Developer Hub and copy its access token from Configure &gt;
                    Authentication. The import can only read conversations that the teammate who installed the app has
                    access to.
                </FieldDescription>
            </Field>
            <QuillImportInboxField
                label="Reply inbox"
                description="Imported tickets are attached to this support inbox so agents can reply to customers by email."
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
