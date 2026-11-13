import { useActions, useValues } from 'kea'

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
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
    Text,
} from '@posthog/quill'

import { TableCombobox } from 'products/data_warehouse/frontend/shared/components/TableCombobox'
import { viewLinkLogic } from 'products/data_warehouse/frontend/shared/logics/viewLinkLogic'

import { JoinKeyControl } from './JoinKeyControl'
import { JoinValidationStatus } from './JoinValidationStatus'

const SQL_EXPRESSION_PLACEHOLDER = 'Enter SQL expression, such as:\n- pdi.distinct_id\n- properties.email'
const FIELD_NAME_INPUT_ID = 'data-catalog-join-field-name'

function SentenceWord({ children }: { children: string }): JSX.Element {
    return (
        <Text size="xs" weight="medium">
            {children}
        </Text>
    )
}

function JoinTables(): JSX.Element {
    const { groupedTableOptions, selectedSourceTableName, selectedJoiningTableName, isNewJoin } =
        useValues(viewLinkLogic)
    const { selectSourceTable, selectJoiningTable, setViewLinkValue } = useActions(viewLinkLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <SentenceWord>Join</SentenceWord>
            {isNewJoin ? (
                <TableCombobox
                    groups={groupedTableOptions}
                    value={selectedSourceTableName}
                    onChange={(tableName) => {
                        setViewLinkValue('source_table_name', tableName)
                        selectSourceTable(tableName)
                    }}
                    aria-label="Source table"
                />
            ) : (
                <span className="font-mono text-xs font-medium">{selectedSourceTableName ?? ''}</span>
            )}
            <SentenceWord>to</SentenceWord>
            <TableCombobox
                groups={groupedTableOptions}
                value={selectedJoiningTableName}
                onChange={(tableName) => {
                    setViewLinkValue('joining_table_name', tableName)
                    selectJoiningTable(tableName)
                }}
                aria-label="Joining table"
            />
        </div>
    )
}

function JoinKeys(): JSX.Element {
    const {
        viewLink,
        sourceKeyMode,
        joiningKeyMode,
        sourceTableKeys,
        joiningTableKeys,
        selectedSourceTable,
        selectedJoiningTable,
        selectedSourceTableName,
        selectedJoiningTableName,
    } = useValues(viewLinkLogic)
    const { setViewLinkValue, selectSourceKey, selectJoiningKey, setSourceKeyMode, setJoiningKeyMode } =
        useActions(viewLinkLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <SentenceWord>where</SentenceWord>
            <JoinKeyControl
                label="Source key"
                mode={sourceKeyMode}
                onModeChange={setSourceKeyMode}
                columnOptions={sourceTableKeys}
                table={selectedSourceTable}
                tableName={selectedSourceTableName}
                value={viewLink.source_table_key ?? null}
                onSelectColumn={(column) => {
                    setViewLinkValue('source_table_key', column)
                    selectSourceKey(column)
                }}
                onExpressionChange={(expression) => setViewLinkValue('source_table_key', expression)}
                sqlPlaceholder={SQL_EXPRESSION_PLACEHOLDER}
            />
            <SentenceWord>=</SentenceWord>
            <JoinKeyControl
                label="Joining key"
                mode={joiningKeyMode}
                onModeChange={setJoiningKeyMode}
                columnOptions={joiningTableKeys}
                table={selectedJoiningTable}
                tableName={selectedJoiningTableName}
                value={viewLink.joining_table_key ?? null}
                onSelectColumn={(column) => {
                    setViewLinkValue('joining_table_key', column)
                    selectJoiningKey(column)
                }}
                onExpressionChange={(expression) => setViewLinkValue('joining_table_key', expression)}
                sqlPlaceholder={SQL_EXPRESSION_PLACEHOLDER}
            />
        </div>
    )
}

function FormErrors(): JSX.Element | null {
    const { showViewLinkErrors, viewLinkErrors } = useValues(viewLinkLogic)
    const messages = [
        ...new Set(Object.values(viewLinkErrors).filter((message): message is string => typeof message === 'string')),
    ]
    if (!showViewLinkErrors || messages.length === 0) {
        return null
    }
    return (
        <FieldError>
            {messages.map((message) => (
                <span key={message} className="block">
                    {message}
                </span>
            ))}
        </FieldError>
    )
}

function FieldNameAndQuery(): JSX.Element | null {
    const { sqlCodeSnippet, fieldName, selectedSourceTableName, selectedJoiningTableName } = useValues(viewLinkLogic)
    const { setFieldName } = useActions(viewLinkLogic)
    if (!sqlCodeSnippet) {
        return null
    }
    return (
        <div className="flex flex-col gap-3 border-t border-border pt-3">
            <Field>
                <FieldLabel htmlFor={FIELD_NAME_INPUT_ID}>Field name</FieldLabel>
                <Input
                    id={FIELD_NAME_INPUT_ID}
                    size="sm"
                    className="max-w-64"
                    value={fieldName}
                    onChange={(event) => setFieldName(event.target.value)}
                    placeholder="Field name"
                />
            </Field>
            <Field>
                <FieldLabel>Query it like this</FieldLabel>
                <pre className="m-0 overflow-x-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
                    {sqlCodeSnippet}
                </pre>
                <FieldDescription>
                    {`How you'll reach ${selectedJoiningTableName} from ${selectedSourceTableName}`}
                </FieldDescription>
            </Field>
        </div>
    )
}

export function JoinEditorDialog(): JSX.Element {
    const { isJoinTableModalOpen, error, isViewLinkSubmitting, saveDisabledReason } = useValues(viewLinkLogic)
    const { toggleJoinTableModal, submitViewLink } = useActions(viewLinkLogic)

    return (
        <Dialog
            open={isJoinTableModalOpen}
            onOpenChange={(open: boolean) => !open && !isViewLinkSubmitting && toggleJoinTableModal()}
        >
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>Join tables</DialogTitle>
                    <DialogDescription>
                        Join two tables or views. Fields from the joined table become available in queries on the source
                        table.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3" data-attr="data-catalog-join-editor">
                        <JoinTables />
                        <JoinKeys />
                        <FormErrors />
                        <JoinValidationStatus />
                        <FieldNameAndQuery />
                        {error && <FieldError>{error}</FieldError>}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" disabled={isViewLinkSubmitting} onClick={() => toggleJoinTableModal()}>
                        Close
                    </Button>
                    <Button
                        variant="primary"
                        loading={isViewLinkSubmitting}
                        disabledReason={saveDisabledReason ?? undefined}
                        onClick={() => submitViewLink()}
                        data-attr="data-catalog-join-save"
                    >
                        Save join
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
