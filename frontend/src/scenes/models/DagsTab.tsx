import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    Tooltip,
} from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils'

import { DataModelingDAG, DataModelingSyncInterval } from '~/types'

import { SYNC_FREQUENCY_OPTIONS, dagsLogic } from './dagsLogic'

const DEFAULT_DAG_NAME = 'Default'

export function DagsTab(): JSX.Element {
    const { dags, dagsLoading } = useValues(dagsLogic)
    const { loadDags, updateDag, deleteDag } = useActions(dagsLogic)

    useEffect(() => {
        loadDags()
    }, [loadDags])

    const columns: LemonTableColumns<DataModelingDAG> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, dag) => (
                <div className="flex flex-col">
                    <span className="font-semibold">{dag.name}</span>
                    {dag.description && <span className="text-muted text-xs">{dag.description}</span>}
                </div>
            ),
        },
        {
            title: 'Models',
            key: 'node_count',
            render: (_, dag) => pluralize(dag.node_count, 'model', 'models'),
        },
        {
            title: 'Sync frequency',
            key: 'sync_frequency',
            render: (_, dag) => (
                <LemonSelect<DataModelingSyncInterval>
                    value={dag.sync_frequency ?? '24hour'}
                    options={SYNC_FREQUENCY_OPTIONS}
                    size="small"
                    onChange={(value) => {
                        if (value && value !== dag.sync_frequency) {
                            updateDag({ ...dag, sync_frequency: value })
                        }
                    }}
                />
            ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, dag) => {
                const isDefault = dag.name === DEFAULT_DAG_NAME
                return (
                    <div className="flex justify-end">
                        <More
                            overlay={
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        fullWidth
                                        onClick={() => openRenameDagDialog({ dag, onSubmit: updateDag })}
                                        disabledReason={isDefault ? 'The default DAG cannot be renamed' : undefined}
                                    >
                                        Rename
                                    </LemonButton>
                                    <Tooltip
                                        title={
                                            isDefault
                                                ? 'The default DAG cannot be deleted.'
                                                : 'Deleting a DAG will also remove all of its model assignments.'
                                        }
                                    >
                                        <LemonButton
                                            type="tertiary"
                                            size="xsmall"
                                            fullWidth
                                            status="danger"
                                            disabledReason={isDefault ? 'The default DAG cannot be deleted' : undefined}
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: `Delete ${dag.name}?`,
                                                    description:
                                                        dag.node_count > 0
                                                            ? `This DAG currently has ${pluralize(dag.node_count, 'model', 'models')} assigned to it. Deleting it will remove those assignments.`
                                                            : 'This action cannot be undone.',
                                                    primaryButton: {
                                                        children: 'Delete',
                                                        status: 'danger',
                                                        onClick: () => deleteDag(dag),
                                                    },
                                                    secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                                })
                                            }}
                                        >
                                            Delete
                                        </LemonButton>
                                    </Tooltip>
                                </>
                            }
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <LemonTable<DataModelingDAG>
            dataSource={dags}
            loading={dagsLoading}
            disableTableWhileLoading={false}
            columns={columns}
            emptyState="No DAGs yet"
            rowKey="id"
            rowClassName="[&>td]:py-2"
        />
    )
}

function openRenameDagDialog({
    dag,
    onSubmit,
}: {
    dag: DataModelingDAG
    onSubmit: (dag: DataModelingDAG) => void
}): void {
    LemonDialog.openForm({
        title: `Rename ${dag.name}`,
        initialValues: {
            name: dag.name,
            description: dag.description ?? '',
        },
        content: (
            <>
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Enter a DAG name" autoFocus />
                </LemonField>
                <LemonField name="description" label="Description" className="mt-2">
                    <LemonInput placeholder="Optional description" />
                </LemonField>
            </>
        ),
        errors: {
            name: (name) => (name?.trim() ? undefined : 'You must enter a DAG name'),
        },
        onSubmit: ({ name, description }) => {
            onSubmit({ ...dag, name: name.trim(), description: description?.trim() ?? '' })
        },
    })
}
