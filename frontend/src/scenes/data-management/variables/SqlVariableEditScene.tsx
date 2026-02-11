import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy, IconInfo } from '@posthog/icons'
import {
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
} from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { sanitizeCodeName } from '~/queries/nodes/DataVisualization/Components/Variables/VariableFields'
import { ListVariable, VariableType } from '~/queries/nodes/DataVisualization/types'

import { VARIABLE_TYPE_OPTIONS, formatVariableReference, getCodeName } from './constants'
import { VARIABLE_INSIGHT_COLUMNS } from './insightColumns'
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
    const { setVariableType, setVariableFormValues, submitVariableForm } = useActions(sqlVariableEditSceneLogic)

    const title = isNew ? 'New variable' : variableForm.name || 'Edit variable'
    const codeNameFallback = getCodeName(variableForm.name ?? '')
    const referenceCodeName = variableForm.code_name || codeNameFallback
    const nameLabel = (
        <span className="inline-flex items-center gap-1">
            Name
            <Tooltip title="Variable name must be alphanumeric and can only contain spaces and underscores">
                <IconInfo className="text-xl text-secondary shrink-0" />
            </Tooltip>
        </span>
    )

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
                            <LemonField name="name" label={nameLabel}>
                                {({ value }) => (
                                    <LemonInput
                                        placeholder="e.g., Start Date"
                                        value={value}
                                        onChange={(newValue) => {
                                            const filteredValue = newValue.replace(/[^a-zA-Z0-9\s_]/g, '')
                                            const shouldUpdateCodeName =
                                                !variableForm.code_name ||
                                                variableForm.code_name === getCodeName(variableForm.name ?? '')
                                            setVariableFormValues({
                                                name: filteredValue,
                                                code_name: shouldUpdateCodeName
                                                    ? getCodeName(filteredValue)
                                                    : variableForm.code_name,
                                            })
                                        }}
                                    />
                                )}
                            </LemonField>

                            {variableForm.name && variableForm.name.length > 0 && (
                                <div className="text-sm text-secondary">
                                    Use this variable by referencing{' '}
                                    <code className="bg-bg-3000 px-1 py-0.5 rounded">
                                        {formatVariableReference(referenceCodeName)}
                                    </code>
                                    <LemonButton
                                        className="inline-block align-middle"
                                        icon={<IconCopy />}
                                        type="tertiary"
                                        size="xsmall"
                                        onClick={() => {
                                            copyToClipboard(formatVariableReference(referenceCodeName), 'code')
                                        }}
                                        tooltip="Copy to clipboard"
                                    />
                                </div>
                            )}

                            <LemonField name="code_name" label="Code name">
                                {({ value, onChange }) => (
                                    <LemonInput
                                        placeholder="start_date"
                                        value={value}
                                        onChange={(newValue) => onChange(sanitizeCodeName(newValue))}
                                    />
                                )}
                            </LemonField>

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
                                    columns={VARIABLE_INSIGHT_COLUMNS}
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
