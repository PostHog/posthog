import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { IconCheckCircle } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonButtonProps,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonTable,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { TableCombobox } from 'scenes/data-warehouse/TableCombobox'
import { JoinKeyMode, KeySelectOption, viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

export type Mode = 'revenue_analytics'
export interface ViewLinkModalProps {
    mode?: Mode
}

const HOGQL_EDITOR_PLACEHOLDER = 'Enter SQL expression, such as:\n- pdi.distinct_id\n- properties.email'
const HOGQL_EDITOR_PLACEHOLDER_REVENUE_ANALYTICS =
    "Enter SQL expression, such as:\n- metadata.customer_id\n- metadata.organization_id\n- concat(email, ',', customer_id)"

interface ModeConfig {
    description: JSX.Element
    lockSourceTable: boolean
    lockJoiningTable: boolean
    lockJoiningKey: boolean
    sourceSqlPlaceholder: string
    showAccessorField: boolean
}

const DEFAULT_MODE_CONFIG: ModeConfig = {
    description: (
        <span>
            Join two tables or views. Fields from the joined table become available in queries on the source table.
        </span>
    ),
    lockSourceTable: false,
    lockJoiningTable: false,
    lockJoiningKey: false,
    sourceSqlPlaceholder: HOGQL_EDITOR_PLACEHOLDER,
    showAccessorField: true,
}

const MODE_CONFIGS: Record<Mode, ModeConfig> = {
    revenue_analytics: {
        description: (
            <span>
                Join either the <code>persons</code> or <code>groups</code> table to the{' '}
                <code>customer_revenue_view</code> Revenue analytics view. Fields from the joined view become available
                in queries at the top level, including the <code>persons.$virt_revenue</code> and{' '}
                <code>persons.$virt_mrr</code> virtual fields.
            </span>
        ),
        lockSourceTable: true,
        lockJoiningTable: true,
        lockJoiningKey: true,
        sourceSqlPlaceholder: HOGQL_EDITOR_PLACEHOLDER_REVENUE_ANALYTICS,
        showAccessorField: false,
    },
}

export function ViewLinkModal({ mode }: ViewLinkModalProps): JSX.Element {
    const { isJoinTableModalOpen } = useValues(viewLinkLogic)
    const { toggleJoinTableModal } = useActions(viewLinkLogic)
    const config = mode ? MODE_CONFIGS[mode] : DEFAULT_MODE_CONFIG

    return (
        <LemonModal
            title="Join tables"
            description={config.description}
            isOpen={isJoinTableModalOpen}
            onClose={toggleJoinTableModal}
            width={900}
        >
            <ViewLinkForm config={config} />
        </LemonModal>
    )
}

export function ViewLinkForm({ config = DEFAULT_MODE_CONFIG }: { config?: ModeConfig }): JSX.Element {
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
        toggleJoinTableModal,
        selectSourceTable,
        setFieldName,
        selectSourceKey,
        selectJoiningKey,
        setSourceKeyMode,
        setJoiningKeyMode,
    } = useActions(viewLinkLogic)

    return (
        <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit>
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Join</span>
                    {config.lockSourceTable || !isNewJoin ? (
                        <span className="font-mono font-medium">{selectedSourceTableName ?? ''}</span>
                    ) : (
                        <Field name="source_table_name">
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
                        </Field>
                    )}
                    <span className="font-medium">to</span>
                    {config.lockJoiningTable ? (
                        <span className="font-mono font-medium">{selectedJoiningTableName ?? ''}</span>
                    ) : (
                        <Field name="joining_table_name">
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
                        </Field>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">where</span>
                    <JoinKeyControl
                        formFieldName="source_table_key"
                        mode={sourceKeyMode}
                        onModeChange={setSourceKeyMode}
                        columnOptions={sourceTableKeys}
                        onSelectColumn={selectSourceKey}
                        tableName={selectedSourceTableName}
                        sqlPlaceholder={config.sourceSqlPlaceholder}
                    />
                    <span className="font-medium">=</span>
                    {config.lockJoiningKey ? (
                        <span className="font-mono font-medium">{selectedJoiningKey ?? ''}</span>
                    ) : (
                        <JoinKeyControl
                            formFieldName="joining_table_key"
                            mode={joiningKeyMode}
                            onModeChange={setJoiningKeyMode}
                            columnOptions={joiningTableKeys}
                            onSelectColumn={selectJoiningKey}
                            tableName={selectedJoiningTableName}
                            sqlPlaceholder={HOGQL_EDITOR_PLACEHOLDER}
                        />
                    )}
                </div>
            </div>
            <JoinValidationStatus />
            {config.showAccessorField && sqlCodeSnippet && (
                <>
                    <LemonDivider className="mt-4 mb-4" />
                    <div className="flex flex-col gap-3 w-full">
                        <div>
                            <span className="l4">Field name</span>
                            <Field name="field_name">
                                <LemonInput
                                    size="small"
                                    className="max-w-64"
                                    value={fieldName}
                                    onChange={(fieldName) => setFieldName(fieldName)}
                                    placeholder="Field name"
                                />
                            </Field>
                        </div>
                        <div>
                            <span className="l4">Query it like this</span>
                            <CodeSnippet className="w-full mt-2" language={Language.SQL}>
                                {sqlCodeSnippet}
                            </CodeSnippet>
                            <div className="text-muted text-xs mt-1">
                                {`How you'll reach ${selectedJoiningTableName} from ${selectedSourceTableName}`}
                            </div>
                        </div>
                    </div>
                </>
            )}
            {error && (
                <div className="flex w-full mt-2">
                    <div className="text-danger flex text-sm overflow-auto">
                        <span>{error}</span>
                    </div>
                </div>
            )}
            <LemonDivider className="mt-4 mb-4" />
            <div className="flex flex-row gap-2 justify-end w-full">
                <LemonButton type="secondary" onClick={toggleJoinTableModal}>
                    Close
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isViewLinkSubmitting}
                    disabledReason={saveDisabledReason ?? undefined}
                >
                    Save join
                </LemonButton>
            </div>
        </Form>
    )
}

const KEY_MODE_OPTIONS: { value: JoinKeyMode; label: string }[] = [
    { value: 'column', label: 'Column' },
    { value: 'sql_expression', label: 'SQL' },
]

interface JoinKeyControlProps {
    formFieldName: 'source_table_key' | 'joining_table_key'
    mode: JoinKeyMode
    onModeChange: (mode: JoinKeyMode) => void
    columnOptions: KeySelectOption[]
    onSelectColumn: (key: string) => void
    tableName: string | null
    sqlPlaceholder: string
}

function JoinKeyControl({
    formFieldName,
    mode,
    onModeChange,
    columnOptions,
    onSelectColumn,
    tableName,
    sqlPlaceholder,
}: JoinKeyControlProps): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <Field name={formFieldName}>
                {({ value, onChange }) =>
                    mode === 'column' ? (
                        <LemonSearchableSelect
                            size="small"
                            onSelect={onSelectColumn}
                            onChange={onChange}
                            value={value ?? undefined}
                            disabledReason={tableName ? '' : 'Select a table first'}
                            options={columnOptions}
                            placeholder="Select a key"
                            searchPlaceholder="Search columns..."
                            // Labels are JSX (name + type tag); the searchable text is the value.
                            searchKeys={['value']}
                            className="min-w-40"
                        />
                    ) : (
                        <HogQLDropdown
                            size="small"
                            hogQLValue={value ?? ''}
                            onHogQLValueChange={onChange}
                            tableName={tableName ?? ''}
                            hogQLEditorPlaceholder={sqlPlaceholder}
                        />
                    )
                }
            </Field>
            <LemonSegmentedButton
                size="small"
                value={mode}
                onChange={onModeChange}
                options={KEY_MODE_OPTIONS}
                disabledReason={tableName ? undefined : 'Select a table first'}
            />
        </div>
    )
}

function JoinMatchPreview(): JSX.Element | null {
    const { joinValidation } = useValues(viewLinkLogic)
    const response = joinValidation.response

    if (joinValidation.status !== 'valid' || !response) {
        return null
    }

    const COLUMN_TITLES: Record<string, string> = {
        source_key: 'Source key',
        joining_key: 'Joining key',
    }
    const columns = (response.columns ?? []).map((column, index) => ({
        title: COLUMN_TITLES[column] ?? column,
        key: column,
        render: (_: any, row: any[]) => <span className="font-mono text-xs">{String(row[index] ?? '')}</span>,
    }))

    return (
        <div className="flex flex-col gap-2">
            {response.match_rate != null && response.total_rows != null && (
                <span className="text-secondary text-sm">
                    {`${Math.round(response.match_rate * 100)}% of ${response.total_rows.toLocaleString()} sampled rows matched`}
                </span>
            )}
            {columns.length > 0 && response.results.length > 0 && (
                <LemonTable
                    size="small"
                    dataSource={response.results}
                    columns={columns}
                    rowKey={(_, index) => String(index)}
                />
            )}
        </div>
    )
}

function JoinValidationStatus(): JSX.Element | null {
    const { joinValidation, keyTypeMismatchWarning } = useValues(viewLinkLogic)

    return (
        <div className="flex flex-col gap-2 mt-2 empty:hidden">
            {keyTypeMismatchWarning && <LemonBanner type="warning">{keyTypeMismatchWarning}</LemonBanner>}
            {joinValidation.status === 'validating' && (
                <div className="flex items-center gap-2 text-secondary">
                    <Spinner />
                    <span>Validating join...</span>
                </div>
            )}
            {joinValidation.status === 'valid' && (
                <>
                    <div className="flex items-center gap-2 text-success">
                        <IconCheckCircle />
                        <span>Join is valid</span>
                    </div>
                    <JoinMatchPreview />
                </>
            )}
            {joinValidation.status === 'valid' && joinValidation.msg && (
                <LemonBanner type="warning">{joinValidation.msg}</LemonBanner>
            )}
            {joinValidation.status === 'error' && (
                <LemonBanner type="error">
                    <div className="flex flex-row items-center justify-between">
                        <div>{joinValidation.msg || 'Could not validate the join.'}</div>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                window.open(
                                    'https://posthog.com/support?utm_medium=in-product&utm_campaign=join-modal-validation-error',
                                    '_blank'
                                )
                            }}
                        >
                            Get help
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}
        </div>
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
    const { reportCustomerAnalyticsAddJoinButtonClicked } = useActions(eventUsageLogic)

    const handleClick = (): void => {
        selectSourceTable(tableName)
        toggleJoinTableModal()
        reportCustomerAnalyticsAddJoinButtonClicked({ table: tableName })
    }

    return (
        <>
            <LemonButton
                children="Join data"
                icon={<IconLink />}
                onClick={handleClick}
                type="primary"
                size="small"
                {...props}
            />
            <ViewLinkModal />
        </>
    )
}
