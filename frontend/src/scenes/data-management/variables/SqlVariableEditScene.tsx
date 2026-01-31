import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ListVariable, VariableType } from '~/queries/nodes/DataVisualization/types'
import { QueryBasedInsightModel } from '~/types'

import { VARIABLE_TYPE_OPTIONS, formatVariableReference, getCodeName } from './constants'
import { SqlVariableEditSceneLogicProps, sqlVariableEditSceneLogic } from './sqlVariableEditSceneLogic'

export const scene: SceneExport<SqlVariableEditSceneLogicProps> = {
    component: SqlVariableEditScene,
    logic: sqlVariableEditSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function VariableTypeFields(): JSX.Element {
    const { variableType, variableForm } = useValues(sqlVariableEditSceneLogic)

    if (variableType === 'String') {
        return (
            <LemonField name="default_value" label="Default value">
                <LemonInput placeholder="Enter default value" />
            </LemonField>
        )
    }

    if (variableType === 'Number') {
        return (
            <LemonField name="default_value" label="Default value">
                <LemonInput type="number" placeholder="Enter default value" />
            </LemonField>
        )
    }

    if (variableType === 'Boolean') {
        return (
            <LemonField name="default_value" label="Default value">
                {({ value, onChange }) => (
                    <LemonSegmentedButton
                        className="w-full"
                        value={value ? 'true' : 'false'}
                        onChange={(val) => onChange(val === 'true')}
                        options={[
                            { value: 'true', label: 'true' },
                            { value: 'false', label: 'false' },
                        ]}
                    />
                )}
            </LemonField>
        )
    }

    if (variableType === 'List') {
        return (
            <>
                <LemonField name="values" label="Options">
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            value={value || []}
                            onChange={onChange}
                            placeholder="Add options..."
                            mode="multiple"
                            allowCustomValues={true}
                            options={[]}
                            sortable={true}
                        />
                    )}
                </LemonField>
                <LemonField name="default_value" label="Default value">
                    {({ value, onChange }) => (
                        <LemonSelect
                            className="w-full"
                            placeholder="Select default value"
                            value={value}
                            options={((variableForm as ListVariable).values || []).map((n: string) => ({
                                label: n,
                                value: n,
                            }))}
                            onChange={(val) => onChange(val ?? '')}
                            allowClear
                            dropdownMaxContentWidth
                        />
                    )}
                </LemonField>
            </>
        )
    }

    if (variableType === 'Date') {
        return (
            <LemonField name="default_value" label="Default value (YYYY-MM-DD)">
                <LemonInput placeholder="e.g., 2024-01-15" />
            </LemonField>
        )
    }

    return <></>
}

export function SqlVariableEditScene(): JSX.Element {
    const {
        isNew,
        variableLoading,
        variableType,
        isVariableFormSubmitting,
        variableForm,
        insightsUsingVariable,
        insightsUsingVariableLoading,
    } = useValues(sqlVariableEditSceneLogic)
    const { setVariableType, submitVariableForm } = useActions(sqlVariableEditSceneLogic)

    const title = isNew ? 'New variable' : variableForm.name || 'Edit variable'

    const insightColumns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <LemonTableLink
                        to={urls.insightView(insight.short_id)}
                        title={name || <i>Untitled</i>}
                        description={insight.description}
                    />
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: function RenderCreated(created_at: string) {
                return created_at ? (
                    <div className="whitespace-nowrap text-right">
                        <TZLabel time={created_at} />
                    </div>
                ) : (
                    <span className="text-secondary">—</span>
                )
            },
            align: 'right',
        },
        {
            title: 'Last modified',
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
        {
            title: 'Last viewed',
            dataIndex: 'last_viewed_at',
            render: function renderLastViewed(last_viewed_at: string | null) {
                return (
                    <div className="whitespace-nowrap">
                        {last_viewed_at ? <TZLabel time={last_viewed_at} /> : <span className="text-muted">Never</span>}
                    </div>
                )
            },
        },
    ]

    return (
        <Form logic={sqlVariableEditSceneLogic} formKey="variableForm" enableFormOnSubmit>
            <SceneContent>
                <SceneTitleSection
                    name={title}
                    resourceType={{ type: 'variable' }}
                    forceBackTo={{
                        path: urls.variables(),
                        name: 'SQL variables',
                        key: 'variables',
                    }}
                    actions={
                        <>
                            <LemonButton
                                data-attr="save-variable"
                                type="primary"
                                size="small"
                                onClick={submitVariableForm}
                                loading={isVariableFormSubmitting}
                            >
                                Save
                            </LemonButton>
                            <LemonButton
                                data-attr="cancel-variable"
                                type="secondary"
                                size="small"
                                to={urls.variables()}
                            >
                                Cancel
                            </LemonButton>
                        </>
                    }
                />

                {variableLoading ? (
                    <div className="space-y-4">
                        <LemonSkeleton className="h-10 w-1/3" />
                        <LemonSkeleton className="h-6 w-1/2" />
                        <LemonSkeleton className="h-30 w-1/2" />
                    </div>
                ) : (
                    <>
                        <div className="space-y-4 max-w-xl">
                            <LemonField
                                name="name"
                                label="Name"
                                info="Variable name must be alphanumeric and can only contain spaces and underscores"
                            >
                                {({ value, onChange }) => (
                                    <LemonInput
                                        placeholder="e.g., Start Date"
                                        value={value}
                                        onChange={(newValue) => {
                                            const filteredValue = newValue.replace(/[^a-zA-Z0-9\s_]/g, '')
                                            onChange(filteredValue)
                                        }}
                                    />
                                )}
                            </LemonField>

                            {variableForm.name && variableForm.name.length > 0 && (
                                <div className="text-sm text-secondary">
                                    Use this variable by referencing{' '}
                                    <code className="bg-bg-3000 px-1 py-0.5 rounded">
                                        {formatVariableReference(getCodeName(variableForm.name))}
                                    </code>
                                </div>
                            )}

                            <LemonField.Pure label="Type">
                                <LemonSelect<VariableType>
                                    value={variableType}
                                    onChange={(value) => value && setVariableType(value)}
                                    options={VARIABLE_TYPE_OPTIONS}
                                />
                            </LemonField.Pure>

                            <VariableTypeFields />
                        </div>

                        {!isNew && (
                            <div className="mt-8">
                                <h3 className="text-base font-semibold mb-4">Insights using this variable</h3>
                                <LemonTable
                                    loading={insightsUsingVariableLoading}
                                    dataSource={insightsUsingVariable}
                                    columns={insightColumns}
                                    rowKey="id"
                                    emptyState="No insights use this variable"
                                />
                            </div>
                        )}
                    </>
                )}
            </SceneContent>
        </Form>
    )
}
