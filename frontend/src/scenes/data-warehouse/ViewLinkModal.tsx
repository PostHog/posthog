import './ViewLinkModal.scss'

import { IconCollapse, IconExpand } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTag,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

import { DatabaseSchemaField, NodeKind } from '~/queries/schema'

export function ViewLinkModal(): JSX.Element {
    const { isJoinTableModalOpen } = useValues(viewLinkLogic)
    const { toggleJoinTableModal } = useActions(viewLinkLogic)

    return (
        <LemonModal
            title="Join tables"
            description={
                <span>
                    Define a join between two tables or views. <b>All</b> fields from the joined table or view will be
                    accessible in queries at the top level without needing to explicitly join the view.
                </span>
            }
            isOpen={isJoinTableModalOpen}
            onClose={toggleJoinTableModal}
            width={700}
        >
            <ViewLinkForm />
        </LemonModal>
    )
}

export function ViewLinkForm(): JSX.Element {
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
            <div className="flex flex-col w-full justify-between items-center">
                <div className="flex flex-row w-full justify-between">
                    <div className="w-60">
                        <span className="l4">Source Table</span>
                        <div className="text-wrap break-all">
                            {isNewJoin ? (
                                <Field name="source_table_name">
                                    <LemonSelect
                                        fullWidth
                                        options={tableOptions}
                                        onSelect={selectSourceTable}
                                        placeholder="Select a table"
                                    />
                                </Field>
                            ) : (
                                selectedSourceTableName ?? ''
                            )}
                        </div>
                    </div>
                    <div className="w-60">
                        <span className="l4">Joining Table</span>
                        <Field name="joining_table_name">
                            <LemonSelect
                                fullWidth
                                options={tableOptions}
                                onSelect={selectJoiningTable}
                                placeholder="Select a table"
                            />
                        </Field>
                    </div>
                </div>
                <div className="mt-4 flex flex-row justify-between items-center w-full">
                    <div className="w-60">
                        <span className="l4">Source Table Key</span>
                        <Field name="source_table_key">
                            <>
                                <LemonSelect
                                    fullWidth
                                    onSelect={selectSourceKey}
                                    value={sourceIsUsingHogQLExpression ? '' : selectedSourceKey ?? undefined}
                                    disabledReason={selectedSourceTableName ? '' : 'Select a table to choose join key'}
                                    options={[...sourceTableKeys, { value: '', label: <span>HogQL Expression</span> }]}
                                    placeholder="Select a key"
                                />
                                {sourceIsUsingHogQLExpression && (
                                    <HogQLDropdown
                                        hogQLValue={selectedSourceKey ?? ''}
                                        onHogQLValueChange={selectSourceKey}
                                        tableName={selectedSourceTableName ?? ''}
                                    />
                                )}
                            </>
                        </Field>
                    </div>
                    <div className="mt-5">
                        <IconSwapHoriz />
                    </div>
                    <div className="w-60">
                        <span className="l4">Joining Table Key</span>
                        <Field name="joining_table_key">
                            <>
                                <LemonSelect
                                    fullWidth
                                    onSelect={selectJoiningKey}
                                    value={joiningIsUsingHogQLExpression ? '' : selectedJoiningKey ?? undefined}
                                    disabledReason={selectedJoiningTableName ? '' : 'Select a table to choose join key'}
                                    options={[...joiningTableKeys, { value: '', label: <span>HogQL Expression</span> }]}
                                    placeholder="Select a key"
                                />
                                {joiningIsUsingHogQLExpression && (
                                    <HogQLDropdown
                                        hogQLValue={selectedJoiningKey ?? ''}
                                        onHogQLValueChange={selectJoiningKey}
                                        tableName={selectedJoiningTableName ?? ''}
                                    />
                                )}
                            </>
                        </Field>
                    </div>
                </div>
                {sqlCodeSnippet && (
                    <div className="w-full mt-2">
                        <LemonDivider className="mt-4 mb-4" />
                        <LemonButton
                            fullWidth
                            onClick={() => setAdvancedSettingsExpanded(!advancedSettingsExpanded)}
                            sideIcon={advancedSettingsExpanded ? <IconCollapse /> : <IconExpand />}
                        >
                            <div>
                                <h3 className="l4 mt-2">Advanced settings</h3>
                                <div className="text-muted mb-2 font-medium">Customize how the fields are accessed</div>
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

const HogQLDropdown = ({
    hogQLValue,
    onHogQLValueChange,
    tableName,
}: {
    hogQLValue: string
    tableName: string
    onHogQLValueChange: (hogQLValue: string) => void
}): JSX.Element => {
    const [isHogQLDropdownVisible, setIsHogQLDropdownVisible] = useState(false)

    return (
        <div className="flex-auto overflow-hidden mt-2">
            <LemonDropdown
                visible={isHogQLDropdownVisible}
                closeOnClickInside={false}
                onClickOutside={() => setIsHogQLDropdownVisible(false)}
                overlay={
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                        <HogQLEditor
                            value={hogQLValue}
                            metadataSource={{ kind: NodeKind.HogQLQuery, query: `SELECT * FROM ${tableName}` }}
                            onChange={(currentValue) => {
                                onHogQLValueChange(currentValue)
                                setIsHogQLDropdownVisible(false)
                            }}
                        />
                    </div>
                }
            >
                <LemonButton
                    fullWidth
                    type="secondary"
                    onClick={() => setIsHogQLDropdownVisible(!isHogQLDropdownVisible)}
                >
                    <code>{hogQLValue}</code>
                </LemonButton>
            </LemonDropdown>
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
