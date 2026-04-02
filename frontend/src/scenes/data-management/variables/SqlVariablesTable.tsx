import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonDialog, LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { VARIABLE_TYPE_LABELS, formatVariableReference } from './constants'
import { sqlVariablesLogic } from './sqlVariablesLogic'

export function SqlVariablesTable(): JSX.Element {
    const { filteredVariables, variablesLoading, searchTerm } = useValues(sqlVariablesLogic)
    const { deleteVariable, setSearchTerm } = useActions(sqlVariablesLogic)

    const handleDelete = (variable: Variable): void => {
        LemonDialog.open({
            title: `Delete variable "${variable.name}"?`,
            description:
                'Are you sure you want to delete this variable? This cannot be undone. Queries that use this variable will no longer work.',
            primaryButton: {
                status: 'danger',
                children: 'Delete variable',
                onClick: () => deleteVariable(variable.id),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const columns: LemonTableColumns<Variable> = [
        {
            title: 'Name',
            key: 'name',
            width: '25%',
            render: function RenderName(_, variable: Variable): JSX.Element {
                return (
                    <Link subtle to={urls.variableEdit(variable.id)}>
                        <span className="font-semibold">{variable.name}</span>
                    </Link>
                )
            },
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Code name',
            key: 'code_name',
            width: '25%',
            tooltip: 'Use this to reference the variable in your SQL query',
            render: function RenderCodeName(_, variable: Variable): JSX.Element {
                return <LemonTag className="font-mono">{formatVariableReference(variable.code_name)}</LemonTag>
            },
            sorter: (a, b) => a.code_name.localeCompare(b.code_name),
        },
        {
            title: 'Type',
            key: 'type',
            width: '15%',
            render: function RenderType(_, variable: Variable): JSX.Element {
                return <LemonTag>{VARIABLE_TYPE_LABELS[variable.type]}</LemonTag>
            },
            sorter: (a, b) => a.type.localeCompare(b.type),
        },
        {
            title: 'Default value',
            key: 'default_value',
            width: '25%',
            render: function RenderDefaultValue(_, variable: Variable): JSX.Element {
                const value = variable.default_value
                if (value === undefined || value === null || value === '') {
                    return <span className="text-secondary">—</span>
                }
                if (typeof value === 'boolean') {
                    return <span>{value ? 'true' : 'false'}</span>
                }
                return <span>{String(value)}</span>
            },
        },
        {
            key: 'actions',
            width: 0,
            render: function RenderActions(_, variable: Variable): JSX.Element {
                return (
                    <div className="flex items-center gap-1">
                        <LemonButton icon={<IconPencil />} size="small" to={urls.variableEdit(variable.id)} />
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            status="danger"
                            onClick={() => handleDelete(variable)}
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="SQL variables"
                description="Create reusable variables for your SQL queries. Use variables to parameterize your queries and make them dynamic."
                resourceType={{ type: 'variable' }}
                actions={
                    <LemonButton type="primary" size="small" to={urls.variableEdit('new')}>
                        New variable
                    </LemonButton>
                }
            />
            <div className="flex flex-row items-center gap-2 justify-start mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search variables..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="w-60"
                />
            </div>
            <LemonTable<Variable>
                data-attr="sql-variables-table"
                rowKey="id"
                dataSource={filteredVariables}
                columns={columns as LemonTableColumn<Variable, keyof Variable | undefined>[]}
                loading={variablesLoading}
                emptyState="No variables yet. Create your first variable to get started."
                defaultSorting={{
                    columnKey: 'name',
                    order: 1,
                }}
                pagination={{ pageSize: 25 }}
            />
        </SceneContent>
    )
}
