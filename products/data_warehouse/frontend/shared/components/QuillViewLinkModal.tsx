import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'
import { useId } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Label,
    Separator,
    Text,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { viewLinkLogic } from '../logics/viewLinkLogic'
import { QuillJoinKeyControl } from './QuillJoinKeyControl'
import { QuillJoinValidationStatus } from './QuillJoinValidationStatus'
import { TableCombobox } from './TableCombobox'
import type { ModeConfig } from './ViewLinkModal'

export function QuillViewLinkModal({
    config,
    joiningSqlPlaceholder,
    isOpen,
    onClose,
}: {
    config: ModeConfig
    joiningSqlPlaceholder: string
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const {
        groupedTableOptions,
        selectedJoiningTableName,
        selectedSourceTableName,
        sourceTableKeys,
        joiningTableKeys,
        sqlCodeSnippet,
        error,
        fieldName,
        isNewJoin,
        selectedJoiningKey,
        sourceKeyMode,
        joiningKeyMode,
        isViewLinkSubmitting,
        saveDisabledReason,
    } = useValues(viewLinkLogic)
    const {
        selectJoiningTable,
        selectSourceTable,
        setFieldName,
        selectSourceKey,
        selectJoiningKey,
        setSourceKeyMode,
        setJoiningKeyMode,
        submitViewLink,
    } = useActions(viewLinkLogic)
    const fieldNameId = useId()

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent size="wide" className="max-w-225">
                <DialogHeader>
                    <DialogTitle>Join tables</DialogTitle>
                    <DialogDescription>{config.description}</DialogDescription>
                </DialogHeader>

                <DialogBody>
                    <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit className="flex flex-col gap-4">
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <Text size="xs" weight="medium" render={<span className="m-0" />}>
                                    Join
                                </Text>
                                {config.lockSourceTable || !isNewJoin ? (
                                    <code className="font-medium">{selectedSourceTableName ?? ''}</code>
                                ) : (
                                    <KeaField name="source_table_name" noStyle>
                                        {({ onChange }) => (
                                            <TableCombobox
                                                groups={groupedTableOptions}
                                                value={selectedSourceTableName}
                                                onChange={(tableName) => {
                                                    onChange(tableName)
                                                    selectSourceTable(tableName)
                                                }}
                                                aria-label="Source table"
                                            />
                                        )}
                                    </KeaField>
                                )}
                                <Text size="xs" weight="medium" render={<span className="m-0" />}>
                                    to
                                </Text>
                                {config.lockJoiningTable ? (
                                    <code className="font-medium">{selectedJoiningTableName ?? ''}</code>
                                ) : (
                                    <KeaField name="joining_table_name" noStyle>
                                        {({ onChange }) => (
                                            <TableCombobox
                                                groups={groupedTableOptions}
                                                value={selectedJoiningTableName}
                                                onChange={(tableName) => {
                                                    onChange(tableName)
                                                    selectJoiningTable(tableName)
                                                }}
                                                aria-label="Joining table"
                                            />
                                        )}
                                    </KeaField>
                                )}
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                                <Text size="xs" weight="medium" render={<span className="m-0" />}>
                                    where
                                </Text>
                                <QuillJoinKeyControl
                                    formFieldName="source_table_key"
                                    mode={sourceKeyMode}
                                    onModeChange={setSourceKeyMode}
                                    columnOptions={sourceTableKeys}
                                    onSelectColumn={selectSourceKey}
                                    tableName={selectedSourceTableName}
                                    sqlPlaceholder={config.sourceSqlPlaceholder}
                                    aria-label="Source key"
                                />
                                <Text size="xs" weight="medium" render={<span className="m-0" />}>
                                    =
                                </Text>
                                {config.lockJoiningKey ? (
                                    <code className="font-medium">{selectedJoiningKey ?? ''}</code>
                                ) : (
                                    <QuillJoinKeyControl
                                        formFieldName="joining_table_key"
                                        mode={joiningKeyMode}
                                        onModeChange={setJoiningKeyMode}
                                        columnOptions={joiningTableKeys}
                                        onSelectColumn={selectJoiningKey}
                                        tableName={selectedJoiningTableName}
                                        sqlPlaceholder={joiningSqlPlaceholder}
                                        aria-label="Joining key"
                                    />
                                )}
                            </div>
                        </div>

                        <QuillJoinValidationStatus />

                        {config.showAccessorField && sqlCodeSnippet && (
                            <>
                                <Separator />
                                <KeaField name="field_name" noStyle>
                                    {({ error: fieldError }) => (
                                        <Field data-invalid={fieldError ? true : undefined}>
                                            <FieldLabel htmlFor={fieldNameId}>Field name</FieldLabel>
                                            <Input
                                                id={fieldNameId}
                                                className="max-w-64"
                                                value={fieldName}
                                                onChange={(event) => setFieldName(event.target.value)}
                                                placeholder="Field name"
                                            />
                                            {fieldError && <FieldError>{fieldError}</FieldError>}
                                        </Field>
                                    )}
                                </KeaField>
                                <div className="flex flex-col gap-2">
                                    <Label>Query it like this</Label>
                                    <CodeSnippet className="w-full" language={Language.SQL}>
                                        {sqlCodeSnippet}
                                    </CodeSnippet>
                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                        {`How you'll reach ${selectedJoiningTableName} from ${selectedSourceTableName}`}
                                    </Text>
                                </div>
                            </>
                        )}

                        {error && (
                            <Text size="xs" variant="destructive" render={<p className="m-0 overflow-auto" />}>
                                {error}
                            </Text>
                        )}
                    </Form>
                </DialogBody>

                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Close
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => submitViewLink()}
                        loading={isViewLinkSubmitting}
                        disabledReason={saveDisabledReason ?? undefined}
                    >
                        Save join
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
