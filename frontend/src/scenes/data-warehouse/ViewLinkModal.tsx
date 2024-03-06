import './ViewLinkModal.scss'

import { IconTrash } from '@posthog/icons'
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
import { HOGQL_IDENTIFIER, viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

import { DatabaseSchemaQueryResponseField } from '~/queries/schema'

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
            width={600}
        >
            <ViewLinkForm />
        </LemonModal>
    )
}

export function ViewLinkForm(): JSX.Element {
    const {
        tableOptions,
        selectedJoiningTable,
        selectedJoiningTableName,
        selectedSourceTableName,
        sourceTableKeys,
        joiningTableKeys,
        sqlCodeSnippet,
        error,
        fieldName,
        isNewJoin,
        selectedSourceKey,
        selectedSourceKeyHogQL,
        selectedJoiningKey,
        selectedJoiningKeyHogQL,
    } = useValues(viewLinkLogic)
    const {
        selectJoiningTable,
        toggleJoinTableModal,
        selectSourceTable,
        setFieldName,
        selectSourceKey,
        selectSourceKeyHogQL,
        selectJoiningKey,
        selectJoiningKeyHogQL,
    } = useActions(viewLinkLogic)

    return (
        <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit>
            <div className="flex flex-col w-full justify-between items-center">
                <div className="flex flex-row w-full justify-between">
                    <div className={isNewJoin ? 'w-50' : 'flex flex-col'}>
                        <span className="l4">Source Table</span>
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
                    <div className="w-50">
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
                <div className="mt-3 flex flex-row justify-between items-center w-full">
                    <div className="w-50">
                        <span className="l4">Source Table Key</span>
                        <Field name="source_table_key">
                            <>
                                <LemonSelect
                                    fullWidth
                                    onSelect={selectSourceKey}
                                    value={selectedSourceKey ?? undefined}
                                    disabledReason={selectedSourceTableName ? '' : 'Select a table to choose join key'}
                                    options={[
                                        ...sourceTableKeys,
                                        { value: HOGQL_IDENTIFIER, label: <span>HogQL Expression</span> },
                                    ]}
                                    placeholder="Select a key"
                                />
                                {selectedSourceKey === HOGQL_IDENTIFIER && (
                                    <HogQLDropdown
                                        hogQLValue={selectedSourceKeyHogQL ?? ''}
                                        onHogQLValueChange={selectSourceKeyHogQL}
                                    />
                                )}
                            </>
                        </Field>
                    </div>
                    <div className="mt-5">
                        <IconSwapHoriz />
                    </div>
                    <div className="w-50">
                        <span className="l4">Joining Table Key</span>
                        <Field name="joining_table_key">
                            <>
                                <LemonSelect
                                    fullWidth
                                    onSelect={selectJoiningKey}
                                    value={selectedJoiningKey ?? undefined}
                                    disabledReason={selectedJoiningTable ? '' : 'Select a table to choose join key'}
                                    options={[
                                        ...joiningTableKeys,
                                        { value: HOGQL_IDENTIFIER, label: <span>HogQL Expression</span> },
                                    ]}
                                    placeholder="Select a key"
                                />
                                {selectedJoiningKey === HOGQL_IDENTIFIER && (
                                    <HogQLDropdown
                                        hogQLValue={selectedJoiningKeyHogQL ?? ''}
                                        onHogQLValueChange={selectJoiningKeyHogQL}
                                    />
                                )}
                            </>
                        </Field>
                    </div>
                </div>
                {sqlCodeSnippet && (
                    <>
                        <LemonDivider className="mt-4 mb-4" />
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
                            <CodeSnippet style={{ width: '100%' }} language={Language.SQL}>
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
                <LemonButton type="primary" htmlType="submit">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}

const HogQLDropdown = ({
    hogQLValue,
    onHogQLValueChange,
}: {
    hogQLValue: string
    onHogQLValueChange: (hogQLValue: string) => void
}): JSX.Element => {
    const [isHogQLDropdownVisible, setIsHogQLDropdownVisible] = useState(false)

    return (
        <div className="flex-auto overflow-hidden">
            <LemonDropdown
                visible={isHogQLDropdownVisible}
                closeOnClickInside={false}
                onClickOutside={() => setIsHogQLDropdownVisible(false)}
                overlay={
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                        <HogQLEditor
                            disablePersonProperties
                            value={hogQLValue}
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

interface ViewLinkDeleteButtonProps {
    table: string
    column: string
}

export function ViewLinkDeleteButton({ table, column }: ViewLinkDeleteButtonProps): JSX.Element {
    const { deleteViewLink } = useActions(viewLinkLogic)

    return (
        <LemonButton
            icon={<IconTrash />}
            onClick={() => deleteViewLink(table, column)}
            tooltip="Remove view association"
            tooltipPlacement="bottom-start"
            size="small"
        />
    )
}

interface KeyLabelProps {
    column: DatabaseSchemaQueryResponseField
}

export function ViewLinkKeyLabel({ column }: KeyLabelProps): JSX.Element {
    return (
        <span>
            {column.key}{' '}
            <LemonTag type="success" className="uppercase">
                {column.type}
            </LemonTag>
        </span>
    )
}
