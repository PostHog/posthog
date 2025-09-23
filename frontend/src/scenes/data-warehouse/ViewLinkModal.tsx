import './ViewLinkModal.scss'

import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonButtonProps,
    LemonCard,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconLink, IconSwapHoriz } from 'lib/lemon-ui/icons'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

interface TablePreviewProps {
    table: DatabaseSchemaTable | undefined
    emptyMessage: string
    previewData?: Record<string, any>[]
    loading?: boolean
    selectedKey?: string | null
}

function TablePreview({
    table,
    emptyMessage,
    previewData = [],
    loading = false,
    selectedKey = null,
}: TablePreviewProps): JSX.Element {
    const columns: LemonTableColumns<Record<string, any>> = table
        ? Object.values(table.fields)
              .filter((column) => column.type !== 'view')
              .map((column) => {
                  const isSelectedKey = selectedKey === column.name
                  return {
                      key: column.name,
                      className: isSelectedKey
                          ? 'bg-warning-highlight border-l-2 border-r-2 border-warning'
                          : undefined,
                      title: (
                          <div className="min-w-0 max-w-32">
                              <div className="font-medium text-xs truncate" title={column.name}>
                                  {column.name}
                              </div>
                              <div className="text-muted text-xxs">{column.type}</div>
                          </div>
                      ),
                      dataIndex: column.name,
                      width: 120,
                      render: (value) => (
                          <div className="text-xs truncate max-w-32" title={String(value || '')}>
                              {value !== null && value !== undefined ? String(value) : '-'}
                          </div>
                      ),
                  }
              })
        : []

    return (
        <div className="flex-1 min-w-0">
            <div className="mt-2 border-t border-border rounded overflow-hidden h-64">
                {table ? (
                    <LemonTable
                        size="small"
                        embedded
                        loading={loading}
                        style={{ width: '100%', height: '100%' }}
                        columns={columns}
                        dataSource={previewData}
                        rowKey={(_, index) => index}
                        emptyState={
                            loading ? null : (
                                <div className="text-muted text-sm text-center p-4">
                                    {previewData.length === 0 ? 'No data available' : 'Loading...'}
                                </div>
                            )
                        }
                    />
                ) : (
                    <div className="h-full flex items-center justify-center text-muted text-sm">{emptyMessage}</div>
                )}
            </div>
        </div>
    )
}

export type Mode = 'revenue_analytics'
export interface ViewLinkModalProps {
    mode?: Mode
}

export function ViewLinkModal({ mode }: ViewLinkModalProps): JSX.Element {
    const { isJoinTableModalOpen } = useValues(viewLinkLogic)
    const { toggleJoinTableModal } = useActions(viewLinkLogic)
    const hasPreviewFlag = useFeatureFlag('DWH_JOIN_TABLE_PREVIEW')

    return (
        <LemonModal
            title="Join tables"
            description={
                mode === 'revenue_analytics' ? (
                    <span>
                        Define a join between either the <code>persons</code> or <code>groups</code> table and the{' '}
                        <code>customer_revenue_view</code> Revenue analytics view. <br />
                        <br />
                        <b>All</b> fields from the joined table or view will be accessible in queries at the top level
                        without needing to explicitly join the view. This will also enable you to see revenue for a
                        person via the <code>persons.$virt_revenue</code> and{' '}
                        <code>persons.$virt_revenue_last_30_days</code> virtual fields.
                    </span>
                ) : (
                    <span>
                        Define a join between two tables or views. <b>All</b> fields from the joined table or view will
                        be accessible in queries at the top level without needing to explicitly join the view.
                    </span>
                )
            }
            isOpen={isJoinTableModalOpen}
            onClose={toggleJoinTableModal}
            width={hasPreviewFlag ? 1200 : 700}
        >
            {hasPreviewFlag ? <ViewLinkFormWithPreview mode={mode} /> : <ViewLinkForm mode={mode} />}
        </LemonModal>
    )
}

const HOGQL_EDITOR_PLACEHOLDER = 'Enter SQL expression, such as:\n- pdi.distinct_id\n- properties.email'
const HOGQL_EDITOR_PLACEHOLDER_REVENUE_ANALYTICS =
    "Enter SQL expression, such as:\n- metadata.customer_id\n- metadata.organization_id\n- concat(email, ',', customer_id)"

export function ViewLinkForm({ mode }: ViewLinkModalProps): JSX.Element {
    const {
        tableOptions,
        selectedJoiningTableName,
        selectedSourceTableName,
        sourceTableKeys,
        joiningTableKeys,
        sqlCodeSnippet,
        error,
        fieldName,
        isNewJoin,
        selectedJoiningKey,
        sourceIsUsingHogQLExpression,
        joiningIsUsingHogQLExpression,
        isViewLinkSubmitting,
        experimentsOptimized,
        experimentsTimestampKey,
    } = useValues(viewLinkLogic)
    const {
        selectJoiningTable,
        toggleJoinTableModal,
        selectSourceTable,
        setFieldName,
        selectSourceKey,
        selectJoiningKey,
        setExperimentsOptimized,
        selectExperimentsTimestampKey,
    } = useActions(viewLinkLogic)
    const [advancedSettingsExpanded, setAdvancedSettingsExpanded] = useState(false)

    return (
        <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit>
            <div className="flex flex-col w-full justify-between items-center">
                <div className="flex flex-row w-full justify-between">
                    <div className="w-60">
                        <span className="l4">Source Table</span>
                        <div className="text-wrap break-all">
                            {mode === 'revenue_analytics' || !isNewJoin ? (
                                (selectedSourceTableName ?? '')
                            ) : (
                                <Field name="source_table_name">
                                    <LemonSelect
                                        fullWidth
                                        options={tableOptions}
                                        onSelect={selectSourceTable}
                                        placeholder="Select a table"
                                    />
                                </Field>
                            )}
                        </div>
                    </div>
                    <div className="w-60">
                        <span className="l4">Joining Table</span>
                        <div className="text-wrap break-all">
                            {mode === 'revenue_analytics' ? (
                                (selectedJoiningTableName ?? '')
                            ) : (
                                <Field name="joining_table_name">
                                    <LemonSearchableSelect
                                        fullWidth
                                        options={tableOptions}
                                        onSelect={selectJoiningTable}
                                        placeholder="Select a table"
                                    />
                                </Field>
                            )}
                        </div>
                    </div>
                </div>
                <div className="mt-4 flex flex-row justify-between items-center w-full">
                    <div className="w-60">
                        <span className="l4">Source Table Key</span>
                        <div className="text-wrap break-all">
                            <Field name="source_table_key">
                                {({ value, onChange }) => (
                                    <>
                                        <LemonSelect
                                            fullWidth
                                            onSelect={selectSourceKey}
                                            onChange={onChange}
                                            value={sourceIsUsingHogQLExpression ? '' : (value ?? undefined)}
                                            disabledReason={
                                                selectedSourceTableName ? '' : 'Select a table to choose join key'
                                            }
                                            options={[
                                                ...sourceTableKeys,
                                                { value: '', label: <span>SQL Expression</span> },
                                            ]}
                                            placeholder="Select a key"
                                        />
                                        {sourceIsUsingHogQLExpression && (
                                            <HogQLDropdown
                                                className="mt-2"
                                                hogQLValue={value}
                                                onHogQLValueChange={onChange}
                                                tableName={selectedSourceTableName ?? ''}
                                                hogQLEditorPlaceholder={
                                                    mode === 'revenue_analytics'
                                                        ? HOGQL_EDITOR_PLACEHOLDER_REVENUE_ANALYTICS
                                                        : HOGQL_EDITOR_PLACEHOLDER
                                                }
                                            />
                                        )}
                                    </>
                                )}
                            </Field>
                        </div>
                    </div>
                    <div className="mt-5">
                        <IconSwapHoriz />
                    </div>
                    <div className="w-60">
                        <span className="l4">Joining Table Key</span>
                        <div className="text-wrap break-all">
                            {mode === 'revenue_analytics' ? (
                                (selectedJoiningKey ?? '')
                            ) : (
                                <Field name="joining_table_key">
                                    {({ value, onChange }) => (
                                        <>
                                            <LemonSelect
                                                fullWidth
                                                onSelect={selectJoiningKey}
                                                onChange={onChange}
                                                value={joiningIsUsingHogQLExpression ? '' : (value ?? undefined)}
                                                disabledReason={
                                                    selectedJoiningTableName ? '' : 'Select a table to choose join key'
                                                }
                                                options={[
                                                    ...joiningTableKeys,
                                                    { value: '', label: <span>SQL Expression</span> },
                                                ]}
                                                placeholder="Select a key"
                                            />
                                            {joiningIsUsingHogQLExpression && (
                                                <HogQLDropdown
                                                    className="mt-2"
                                                    hogQLValue={value}
                                                    onHogQLValueChange={onChange}
                                                    tableName={selectedJoiningTableName ?? ''}
                                                    hogQLEditorPlaceholder={HOGQL_EDITOR_PLACEHOLDER}
                                                />
                                            )}
                                        </>
                                    )}
                                </Field>
                            )}
                        </div>
                    </div>
                </div>
                {'events' === selectedJoiningTableName && (
                    <div className="w-full mt-2">
                        <LemonDivider className="mt-4 mb-4" />
                        <div className="mt-4 flex flex-row justify-between w-full">
                            <div className="mr-4">
                                <span className="l4">Optimize for Experiments</span>
                                <Field name="experiments_optimized">
                                    <LemonCheckbox
                                        className="mt-2"
                                        checked={experimentsOptimized}
                                        onChange={(checked) => setExperimentsOptimized(checked)}
                                        fullWidth
                                        label="Limit join to most recent matching event based on&nbsp;timestamp"
                                    />
                                </Field>
                            </div>
                            <div className="w-60 shrink-0">
                                <span className="l4">Source Timestamp Key</span>
                                <Field name="experiments_timestamp_key">
                                    <LemonSelect
                                        fullWidth
                                        onSelect={selectExperimentsTimestampKey}
                                        value={experimentsTimestampKey ?? undefined}
                                        options={sourceTableKeys}
                                        placeholder="Select a key"
                                    />
                                </Field>
                            </div>
                        </div>
                    </div>
                )}
                {sqlCodeSnippet && mode !== 'revenue_analytics' && (
                    <div className="w-full mt-2">
                        <LemonDivider className="mt-4 mb-4" />
                        <LemonButton
                            fullWidth
                            onClick={() => setAdvancedSettingsExpanded(!advancedSettingsExpanded)}
                            sideIcon={advancedSettingsExpanded ? <IconCollapse /> : <IconExpand />}
                        >
                            <div>
                                <h3 className="l4 mt-2">Advanced settings</h3>
                                <div className="text-secondary mb-2 font-medium">
                                    Customize how the fields are accessed
                                </div>
                            </div>
                        </LemonButton>
                    </div>
                )}
                {sqlCodeSnippet && advancedSettingsExpanded && (
                    <>
                        <div className="mt-3 flex flex-row justify-between items-center w-full">
                            <div className="w-full">
                                <span className="l4">Field Name</span>
                                <Field
                                    name="field_name"
                                    hint={`Pick a field name to access ${selectedJoiningTableName} from ${selectedSourceTableName}`}
                                >
                                    <LemonInput
                                        value={fieldName}
                                        onChange={(fieldName) => setFieldName(fieldName)}
                                        placeholder="Field name"
                                    />
                                </Field>
                            </div>
                        </div>
                        <div className="mt-4 flex w-full">
                            <CodeSnippet className="w-full" language={Language.SQL}>
                                {sqlCodeSnippet}
                            </CodeSnippet>
                        </div>
                    </>
                )}
                {error && (
                    <div className="flex w-full">
                        <div className="text-danger flex text-sm overflow-auto">
                            <span>{error}</span>
                        </div>
                    </div>
                )}
            </div>
            <LemonDivider className="mt-4 mb-4" />
            <div className="flex flex-row justify-end w-full">
                <LemonButton className="mr-3" type="secondary" onClick={toggleJoinTableModal}>
                    Close
                </LemonButton>
                <LemonButton type="primary" htmlType="submit" loading={isViewLinkSubmitting}>
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}

export function ViewLinkFormWithPreview({ mode }: ViewLinkModalProps): JSX.Element {
    const {
        tableOptions,
        selectedJoiningTableName,
        selectedSourceTableName,
        sourceTableKeys,
        joiningTableKeys,
        sqlCodeSnippet,
        error,
        fieldName,
        isNewJoin,
        selectedSourceKey,
        selectedJoiningKey,
        sourceIsUsingHogQLExpression,
        joiningIsUsingHogQLExpression,
        isViewLinkSubmitting,
        experimentsOptimized,
        experimentsTimestampKey,
        selectedSourceTable,
        selectedJoiningTable,
        sourceTablePreviewData,
        joiningTablePreviewData,
        sourceTablePreviewLoading,
        joiningTablePreviewLoading,
        isJoinValidating,
        isJoinValid,
        validationError,
        validationWarning,
    } = useValues(viewLinkLogic)
    const {
        selectJoiningTable,
        selectSourceTable,
        setFieldName,
        selectSourceKey,
        selectJoiningKey,
        setExperimentsOptimized,
        selectExperimentsTimestampKey,
        validateJoin,
    } = useActions(viewLinkLogic)
    const [advancedSettingsExpanded, setAdvancedSettingsExpanded] = useState(false)

    return (
        <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit>
            <div className="flex flex-row items-start justify-between gap-4">
                <LemonCard className="flex-1 p-0 max-w-136">
                    <div className="flex flex-col gap-4 p-4">
                        <div title="source-table-name-and-key" className="flex flex-row gap-4">
                            <div title="source-table-name" className="flex-1">
                                <span className="l4">Source Table</span>
                                <div className="text-wrap break-all mt-2">
                                    {mode === 'revenue_analytics' || !isNewJoin ? (
                                        <div>{selectedSourceTableName ?? ''}</div>
                                    ) : (
                                        <Field name="source_table_name">
                                            <LemonSelect
                                                fullWidth
                                                options={tableOptions}
                                                onSelect={selectSourceTable}
                                                placeholder="Select a table"
                                            />
                                        </Field>
                                    )}
                                </div>
                            </div>
                            <div title="source-table-key" className="flex-1">
                                <span className="l4">Source Table Key</span>
                                <div className="text-wrap break-all mt-2">
                                    <Field name="source_table_key">
                                        {({ value, onChange }) => (
                                            <div className="flex flex-col gap-2">
                                                <LemonSelect
                                                    fullWidth
                                                    onSelect={selectSourceKey}
                                                    onChange={onChange}
                                                    value={sourceIsUsingHogQLExpression ? '' : (value ?? undefined)}
                                                    disabledReason={
                                                        selectedSourceTableName
                                                            ? ''
                                                            : 'Select a table to choose join key'
                                                    }
                                                    options={[
                                                        ...sourceTableKeys,
                                                        { value: '', label: <span>SQL Expression</span> },
                                                    ]}
                                                    placeholder="Select a key"
                                                />
                                                {sourceIsUsingHogQLExpression && (
                                                    <div className="flex-1">
                                                        <HogQLDropdown
                                                            hogQLValue={value ?? ''}
                                                            onHogQLValueChange={onChange}
                                                            tableName={selectedSourceTableName ?? ''}
                                                            hogQLEditorPlaceholder={
                                                                mode === 'revenue_analytics'
                                                                    ? HOGQL_EDITOR_PLACEHOLDER_REVENUE_ANALYTICS
                                                                    : HOGQL_EDITOR_PLACEHOLDER
                                                            }
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </Field>
                                </div>
                            </div>
                        </div>
                    </div>
                    {selectedSourceTable && (
                        <TablePreview
                            table={selectedSourceTable}
                            emptyMessage="Select a source table to view preview"
                            previewData={sourceTablePreviewData}
                            loading={sourceTablePreviewLoading}
                            selectedKey={selectedSourceKey}
                        />
                    )}
                </LemonCard>

                <div className="flex items-center mt-16">
                    <IconSwapHoriz />
                </div>

                <LemonCard className="flex-1 p-0 max-w-136">
                    <div className="flex flex-col gap-4 p-4">
                        <div title="joining-table-name-and-key" className="flex flex-row gap-4">
                            <div title="joining-table-name" className="flex-1">
                                <span className="l4">Joining Table</span>
                                <div className="text-wrap break-all mt-2">
                                    {mode === 'revenue_analytics' ? (
                                        <div>{selectedJoiningTableName ?? ''}</div>
                                    ) : (
                                        <Field name="joining_table_name">
                                            <LemonSearchableSelect
                                                fullWidth
                                                options={tableOptions}
                                                onSelect={selectJoiningTable}
                                                placeholder="Select a table"
                                            />
                                        </Field>
                                    )}
                                </div>
                            </div>
                            <div title="joining-table-key" className="flex-1">
                                <span className="l4">Joining Table Key</span>
                                <div className="text-wrap break-all mt-2">
                                    {mode === 'revenue_analytics' ? (
                                        <div className="h-10 flex items-center px-3 py-2">
                                            {selectedJoiningKey ?? ''}
                                        </div>
                                    ) : (
                                        <Field name="joining_table_key">
                                            {({ value, onChange }) => (
                                                <div className="flex flex-col gap-2">
                                                    <LemonSelect
                                                        fullWidth
                                                        onSelect={selectJoiningKey}
                                                        onChange={onChange}
                                                        value={
                                                            joiningIsUsingHogQLExpression ? '' : (value ?? undefined)
                                                        }
                                                        disabledReason={
                                                            selectedJoiningTableName
                                                                ? ''
                                                                : 'Select a table to choose join key'
                                                        }
                                                        options={[
                                                            ...joiningTableKeys,
                                                            { value: '', label: <span>SQL Expression</span> },
                                                        ]}
                                                        placeholder="Select a key"
                                                    />
                                                    {joiningIsUsingHogQLExpression && (
                                                        <div className="flex-1">
                                                            <HogQLDropdown
                                                                hogQLValue={value ?? ''}
                                                                onHogQLValueChange={onChange}
                                                                tableName={selectedJoiningTableName ?? ''}
                                                                hogQLEditorPlaceholder={HOGQL_EDITOR_PLACEHOLDER}
                                                            />
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </Field>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div className="space-y-4">
                        {selectedJoiningTable && (
                            <TablePreview
                                table={selectedJoiningTable}
                                emptyMessage="Select a joining table to view preview"
                                previewData={joiningTablePreviewData}
                                loading={joiningTablePreviewLoading}
                                selectedKey={selectedJoiningKey}
                            />
                        )}
                    </div>
                </LemonCard>
            </div>
            <div className="w-full mt-4">
                {'events' === selectedJoiningTableName && (
                    <div className="w-full mt-2">
                        <LemonDivider className="mt-4 mb-4" />
                        <div className="mt-4 flex flex-row justify-between w-full">
                            <div className="mr-4">
                                <span className="l4">Optimize for Experiments</span>
                                <Field name="experiments_optimized">
                                    <LemonCheckbox
                                        className="mt-2"
                                        checked={experimentsOptimized}
                                        onChange={(checked) => setExperimentsOptimized(checked)}
                                        fullWidth
                                        label="Limit join to most recent matching event based on&nbsp;timestamp"
                                    />
                                </Field>
                            </div>
                            <div className="w-60 shrink-0">
                                <span className="l4">Source Timestamp Key</span>
                                <Field name="experiments_timestamp_key">
                                    <LemonSelect
                                        fullWidth
                                        onSelect={selectExperimentsTimestampKey}
                                        value={experimentsTimestampKey ?? undefined}
                                        options={sourceTableKeys}
                                        placeholder="Select a key"
                                    />
                                </Field>
                            </div>
                        </div>
                    </div>
                )}
                {sqlCodeSnippet && mode !== 'revenue_analytics' && (
                    <div className="w-full mt-2">
                        <LemonDivider className="mt-4 mb-4" />
                        <LemonButton
                            fullWidth
                            onClick={() => setAdvancedSettingsExpanded(!advancedSettingsExpanded)}
                            sideIcon={advancedSettingsExpanded ? <IconCollapse /> : <IconExpand />}
                        >
                            <div>
                                <h3 className="l4 mt-2">Advanced settings</h3>
                                <div className="text-secondary mb-2 font-medium">
                                    Customize how the fields are accessed
                                </div>
                            </div>
                        </LemonButton>
                    </div>
                )}
                {sqlCodeSnippet && advancedSettingsExpanded && (
                    <>
                        <div className="mt-3 flex flex-row justify-between items-center w-full">
                            <div className="w-full">
                                <span className="l4">Field Name</span>
                                <Field
                                    name="field_name"
                                    hint={`Pick a field name to access ${selectedJoiningTableName} from ${selectedSourceTableName}`}
                                >
                                    <LemonInput
                                        value={fieldName}
                                        onChange={(fieldName) => setFieldName(fieldName)}
                                        placeholder="Field name"
                                    />
                                </Field>
                            </div>
                        </div>
                        <div className="mt-4 flex w-full">
                            <CodeSnippet className="w-full" language={Language.SQL}>
                                {sqlCodeSnippet}
                            </CodeSnippet>
                        </div>
                    </>
                )}
                {error && (
                    <div className="flex w-full">
                        <div className="text-danger flex text-sm overflow-auto">
                            <span>{error}</span>
                        </div>
                    </div>
                )}
            </div>
            {validationError && (
                <LemonBanner
                    className="mt-2"
                    type="error"
                    children={
                        <div className="flex flex-row items-center justify-between">
                            <div>
                                Validation error:
                                <br />
                                {validationError}
                            </div>
                            <LemonButton
                                children="Get help"
                                type="secondary"
                                onClick={() => {
                                    window.open(
                                        'https://posthog.com/support?utm_medium=in-product&utm_campaign=join-modal-validation-error',
                                        '_blank'
                                    )
                                }}
                            />
                        </div>
                    }
                />
            )}
            {validationWarning && <LemonBanner className="mt-2" type="warning" children={validationWarning} />}
            <LemonDivider className="mt-4 mb-4" />
            <div className="flex flex-row gap-2 justify-end w-full">
                {isJoinValid ? (
                    <>
                        <LemonButton disabledReason="Join is valid">Join is valid</LemonButton>
                        <LemonButton type="primary" htmlType="submit" loading={isViewLinkSubmitting}>
                            Save join
                        </LemonButton>
                    </>
                ) : (
                    <>
                        <LemonButton htmlType="submit" loading={isViewLinkSubmitting} disabledReason={validationError}>
                            Save join without validating
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={validateJoin}
                            loading={isJoinValidating}
                            disabledReason={validationError || validationWarning}
                        >
                            Validate join
                        </LemonButton>
                    </>
                )}
            </div>
        </Form>
    )
}

interface KeyLabelProps {
    column: DatabaseSchemaField
}

export function ViewLinkKeyLabel({ column }: KeyLabelProps): JSX.Element {
    return (
        <span>
            {column.name}{' '}
            <LemonTag type="success" className="uppercase">
                {column.type}
            </LemonTag>
        </span>
    )
}

type ViewLinkButtonProps = LemonButtonProps & {
    tableName: string
}

export function ViewLinkButton({ tableName, ...props }: ViewLinkButtonProps): JSX.Element {
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)

    const handleClick = (): void => {
        selectSourceTable(tableName)
        toggleJoinTableModal()
    }

    return (
        <>
            <LemonButton children="Join data" icon={<IconLink />} onClick={handleClick} type="primary" {...props} />
            <ViewLinkModal />
        </>
    )
}
