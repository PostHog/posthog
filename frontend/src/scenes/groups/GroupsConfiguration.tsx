import {
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { useState } from 'react'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { HogQLDropdown } from 'scenes/data-warehouse/ViewLinkModal'
import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseViewLink } from '~/types'

import { groupsConfigurationLogic } from './groupsConfigurationLogic'
import { groupsListLogic } from './groupsListLogic'
export function Snippet({ singular }: { singular: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.group('${singular}', 'id:5', {\n` +
                `    name: 'Awesome ${singular}',\n` +
                '    value: 11\n' +
                '});'}
        </CodeSnippet>
    )
}

export function GroupJoinModal({
    groupTypeIndex,
    isOpen,
    onClose,
}: {
    groupTypeIndex: number
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const {
        groupTypeName: { singular, plural },
    } = useValues(groupsListLogic({ groupTypeIndex }))
    const {
        tableOptionsWarehouseOnly,
        selectedJoiningTableName,
        joiningTableKeys,
        selectedSourceKey,
        selectedJoiningKey,
        sourceIsUsingHogQLExpression,
        joiningIsUsingHogQLExpression,
        isViewLinkSubmitting,
    } = useValues(viewLinkLogic)
    const { selectJoiningTable, selectSourceKey, selectJoiningKey } = useActions(viewLinkLogic)

    return (
        <LemonModal
            title={`Join table onto ${plural}`}
            description={
                <span>
                    Define a join between {plural} and any table or view. <b>All</b> fields from the joined table or
                    view will be accessible in queries at the top level without needing to explicitly join the view.
                </span>
            }
            isOpen={isOpen}
            onClose={onClose}
            width={700}
        >
            <Form logic={viewLinkLogic} formKey="groupViewLink" enableFormOnSubmit>
                <div className="grid grid-cols-3 gap-4 h-full">
                    {/* <div className="flex flex-row w-full justify-between"> */}
                    {/* <div className="mt-4 flex flex-row justify-between items-center w-full"> */}
                    <div className="flex flex-col">
                        <div className="flex-1">
                            <span className="l4">Joining Table</span>
                            <div className="text-wrap break-all">{plural}</div>
                            <br />
                            <br />
                        </div>
                        <div className="flex-1">
                            <span className="l4">Property to join on</span>
                            <Field name="source_table_key">
                                <LemonRadio
                                    onChange={(newValue) => newValue == 'key' && selectSourceKey('key')}
                                    value={!selectedSourceKey || selectedSourceKey === 'key' ? 'key' : 'property'}
                                    options={[
                                        { value: 'key', label: `${singular} key` },
                                        {
                                            value: 'property',
                                            label: (
                                                <PropertySelect
                                                    onChange={(property) =>
                                                        selectSourceKey(`properties.\`${property}\``)
                                                    }
                                                    selectedProperties={
                                                        sourceIsUsingHogQLExpression && selectedSourceKey
                                                            ? [selectedSourceKey.replace('property.`', '').slice(0, -1)]
                                                            : []
                                                    }
                                                    addText="select property"
                                                    taxonomicFilterGroup={`${TaxonomicFilterGroupType.GroupsPrefix}_${groupTypeIndex}`}
                                                />
                                            ),
                                        },
                                    ]}
                                />
                            </Field>
                        </div>
                    </div>
                    <div className="row-span-2  flex items-center justify-center">
                        <IconSwapHoriz className="w-10 h-10" />
                    </div>

                    <div className="flex flex-col">
                        <div className="flex-1">
                            <span className="l4">Joining Table</span>
                            <Field name="joining_table_name">
                                <LemonSelect
                                    fullWidth
                                    options={tableOptionsWarehouseOnly}
                                    onSelect={selectJoiningTable}
                                    placeholder="Select a table"
                                />
                            </Field>
                        </div>
                        <div className="flex-1">
                            <span className="l4">Joining Table Key</span>
                            <Field name="joining_table_key">
                                <>
                                    <LemonSelect
                                        fullWidth
                                        onSelect={selectJoiningKey}
                                        value={joiningIsUsingHogQLExpression ? '' : selectedJoiningKey ?? undefined}
                                        disabledReason={
                                            selectedJoiningTableName ? '' : 'Select a table to choose join key'
                                        }
                                        options={[
                                            ...joiningTableKeys,
                                            { value: '', label: <span>HogQL Expression</span> },
                                        ]}
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
                </div>
                <LemonDivider className="mt-4 mb-4" />
                <div className="flex flex-row justify-end w-full">
                    <LemonButton className="mr-3" type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" htmlType="submit" loading={isViewLinkSubmitting}>
                        Save
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}

function JoinTable({ groupTypeIndex }: { groupTypeIndex: number }): JSX.Element {
    const logic = groupsConfigurationLogic({ groupTypeIndex })
    const { joins } = useValues(logic)

    const { loadJoins } = useActions(dataWarehouseJoinsLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)
    const { allTables } = useValues(databaseTableListLogic)

    const { currentTeamId } = useValues(teamLogic)

    return joins.length > 0 ? (
        <LemonTable
            dataSource={joins}
            columns={[
                { title: 'Join table', dataIndex: 'joining_table_name' },
                {
                    title: 'Join definition',
                    render: (_, join) => (
                        <>
                            <code>
                                {singular}.{join.source_table_key}
                            </code>{' '}
                            <IconSwapHoriz />{' '}
                            <code>
                                {join.joining_table_name}.{join.joining_table_key}
                            </code>
                        </>
                    ),
                },
                {
                    title: 'Joined fields',
                    tooltip: 'All fields that are joined onto this group type',
                    render: (_, join) => (
                        <>
                            {join.joining_table_name && (
                                <DatabaseTable
                                    table={join.joining_table_name}
                                    tables={allTables}
                                    inEditSchemaMode={false}
                                />
                            )}
                        </>
                    ),
                },
                createdAtColumn() as LemonTableColumn<DataWarehouseViewLink, keyof DataWarehouseViewLink | undefined>,
                createdByColumn() as LemonTableColumn<DataWarehouseViewLink, keyof DataWarehouseViewLink | undefined>,
                {
                    key: 'actions',
                    width: 0,
                    render: function RenderActions(_, join) {
                        return (
                            <div className="flex flex-row justify-end">
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                status="danger"
                                                data-attr="delete-join"
                                                key="delete-join"
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Delete join?',
                                                        description: 'Are you sure you want to delete this join?',

                                                        primaryButton: {
                                                            children: 'Delete',
                                                            status: 'danger',
                                                            onClick: () =>
                                                                void deleteWithUndo({
                                                                    endpoint: `projects/${currentTeamId}/warehouse_view_link`,
                                                                    object: {
                                                                        id: join.id,
                                                                        name: `${join.field_name} on ${join.source_table_name}`,
                                                                    },
                                                                    callback: () => {
                                                                        loadDatabase()
                                                                        loadJoins()
                                                                    },
                                                                }),
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                        },
                                                    })
                                                }}
                                            >
                                                Delete
                                            </LemonButton>
                                        </>
                                    }
                                />
                            </div>
                        )
                    },
                },
            ]}
        />
    ) : (
        <></>
    )
}

export function GroupsConfiguration({ groupTypeIndex }: { groupTypeIndex: number }): JSX.Element {
    const {
        groupTypeName: { singular, plural },
    } = useValues(groupsListLogic({ groupTypeIndex }))
    const [isJoinTableModalOpen, toggleJoinTableModal] = useState(false)

    const { dataWarehouseTables } = useValues(databaseTableListLogic)

    return (
        <>
            <p>
                <h2>Sending {plural} data</h2>
                Make sure you correctly send group information:
                <Snippet singular={singular} />
            </p>

            <p>
                <h2>Pull in data from other sources</h2>
                <p>
                    Using the PostHog Data warehouse, you can add data from Stripe, Postgres, Hubspot, Salesforce and
                    many other sources onto your {plural}. You can then query or display that data.
                </p>

                <p>
                    <h4>Step 1: add sources to the Data warehouse</h4>
                    <LemonButton className="inline-block w-auto" to="/pipeline/new/source" type="primary">
                        Add a data warehouse source
                    </LemonButton>
                    <br />
                    <br />

                    <h4>Step 2: join the data onto {plural}</h4>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            dataWarehouseTables.length === 0 ? 'You need to add a Data warehouse source first' : ''
                        }
                        onClick={() => toggleJoinTableModal(true)}
                    >
                        Add a join onto {plural}
                    </LemonButton>
                    <br />
                    <br />
                </p>
                <GroupJoinModal
                    groupTypeIndex={groupTypeIndex}
                    isOpen={isJoinTableModalOpen}
                    onClose={() => toggleJoinTableModal(false)}
                />
                <JoinTable groupTypeIndex={groupTypeIndex} />
            </p>
        </>
    )
}
