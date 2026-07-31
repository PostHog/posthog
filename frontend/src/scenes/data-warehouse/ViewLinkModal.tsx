import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { useState } from 'react'

import { IconCheckCircle, IconCollapse, IconExpand } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonButtonProps,
    LemonCard,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonSelect,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { TablePreview } from 'lib/components/TablePreview/TablePreview'
import { IconLink, IconSwapHoriz } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

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
    showAdvancedSettings: boolean
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
    showAdvancedSettings: true,
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
        showAdvancedSettings: false,
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
            width={1200}
        >
            <ViewLinkForm config={config} />
        </LemonModal>
    )
}

export function ViewLinkForm({ config = DEFAULT_MODE_CONFIG }: { config?: ModeConfig }): JSX.Element {
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
        selectedSourceTable,
        selectedJoiningTable,
        sourceTablePreviewData,
        joiningTablePreviewData,
        sourceTablePreviewLoading,
        joiningTablePreviewLoading,
        saveDisabledReason,
    } = useValues(viewLinkLogic)
    const {
        selectJoiningTable,
        toggleJoinTableModal,
        selectSourceTable,
        setFieldName,
        selectSourceKey,
        selectJoiningKey,
    } = useActions(viewLinkLogic)
    const [advancedSettingsExpanded, setAdvancedSettingsExpanded] = useState(false)

    return (
        <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit>
            <div className="flex flex-row items-start justify-between gap-4">
                <LemonCard className="flex-1 p-0 max-w-136">
                    <div className="flex flex-col gap-4 p-4">
                        <div title="source-table-name-and-key" className="flex flex-row gap-4">
                            <div title="source-table-name" className="flex-1">
                                <span className="l4">Source table</span>
                                <div className="text-wrap break-all mt-2">
                                    {config.lockSourceTable || !isNewJoin ? (
                                        <div>{selectedSourceTableName ?? ''}</div>
                                    ) : (
                                        <Field name="source_table_name">
                                            <LemonSearchableSelect
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
                                <span className="l4">Source table key</span>
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
                                                            : 'Select a table to choose a join key'
                                                    }
                                                    options={[
                                                        ...sourceTableKeys,
                                                        { value: '', label: <span>SQL expression</span> },
                                                    ]}
                                                    placeholder="Select a key"
                                                />
                                                {sourceIsUsingHogQLExpression && (
                                                    <div className="flex-1">
                                                        <HogQLDropdown
                                                            hogQLValue={value ?? ''}
                                                            onHogQLValueChange={onChange}
                                                            tableName={selectedSourceTableName ?? ''}
                                                            hogQLEditorPlaceholder={config.sourceSqlPlaceholder}
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
                    <div className="pt-2">
                        {selectedSourceTable && (
                            <TablePreview
                                table={selectedSourceTable}
                                emptyMessage="Select a source table to view preview"
                                previewData={sourceTablePreviewData}
                                loading={sourceTablePreviewLoading}
                                selectedKey={selectedSourceKey}
                            />
                        )}
                    </div>
                </LemonCard>

                <div className="flex items-center mt-16">
                    <IconSwapHoriz />
                </div>

                <LemonCard className="flex-1 p-0 max-w-136">
                    <div className="flex flex-col gap-4 p-4">
                        <div title="joining-table-name-and-key" className="flex flex-row gap-4">
                            <div title="joining-table-name" className="flex-1">
                                <span className="l4">Joining table</span>
                                <div className="text-wrap break-all mt-2">
                                    {config.lockJoiningTable ? (
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
                                <span className="l4">Joining table key</span>
                                <div className="text-wrap break-all mt-2">
                                    {config.lockJoiningKey ? (
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
                                                                : 'Select a table to choose a join key'
                                                        }
                                                        options={[
                                                            ...joiningTableKeys,
                                                            { value: '', label: <span>SQL expression</span> },
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
                    <div className="space-y-4 pt-2">
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
                {config.showAdvancedSettings && sqlCodeSnippet && (
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
                {config.showAdvancedSettings && sqlCodeSnippet && advancedSettingsExpanded && (
                    <>
                        <div className="mt-3 flex flex-row justify-between items-center w-full">
                            <div className="w-full">
                                <span className="l4">Field name</span>
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
            <JoinValidationStatus />
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
                <div className="flex items-center gap-2 text-success">
                    <IconCheckCircle />
                    <span>Join is valid</span>
                </div>
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
