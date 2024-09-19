import { closestCenter, DndContext } from '@dnd-kit/core'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconGear, IconInfo, IconLock, IconPlus, IconTrash, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorInline, CodeEditorInlineProps } from 'lib/monaco/CodeEditorInline'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'

import { HogFunctionInputSchemaType, HogFunctionInputType } from '~/types'

import { EmailTemplater } from './email-templater/EmailTemplater'
import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { HogFunctionInputIntegration } from './integrations/HogFunctionInputIntegration'
import { HogFunctionInputIntegrationField } from './integrations/HogFunctionInputIntegrationField'

export type HogFunctionInputProps = {
    schema: HogFunctionInputSchemaType
    value?: any
    onChange?: (value: any) => void
    disabled?: boolean
}

export type HogFunctionInputWithSchemaProps = {
    schema: HogFunctionInputSchemaType
}

const typeList = ['string', 'boolean', 'dictionary', 'choice', 'json', 'integration', 'email'] as const

function JsonConfigField(props: {
    onChange?: (value: string) => void
    className?: string
    autoFocus?: boolean
    value?: string
}): JSX.Element {
    const { globalsWithInputs } = useValues(hogFunctionConfigurationLogic)
    return (
        <CodeEditorResizeable
            language="hogJson"
            value={typeof props.value !== 'string' ? JSON.stringify(props.value, null, 2) : props.value}
            onChange={(v) => props.onChange?.(v ?? '')}
            options={{
                lineNumbers: 'off',
                minimap: {
                    enabled: false,
                },
                scrollbar: {
                    vertical: 'hidden',
                    verticalScrollbarSize: 0,
                },
            }}
            globals={globalsWithInputs}
        />
    )
}

function EmailTemplateField({ schema }: { schema: HogFunctionInputSchemaType }): JSX.Element {
    const { globalsWithInputs, logicProps } = useValues(hogFunctionConfigurationLogic)

    return (
        <>
            <EmailTemplater
                formLogic={hogFunctionConfigurationLogic}
                formLogicProps={logicProps}
                formKey="configuration"
                formFieldsPrefix={`inputs.${schema.key}.value`}
                globals={globalsWithInputs}
            />
        </>
    )
}

function HogFunctionTemplateInput(props: Omit<CodeEditorInlineProps, 'globals'>): JSX.Element {
    const { globalsWithInputs } = useValues(hogFunctionConfigurationLogic)
    return <CodeEditorInline {...props} globals={globalsWithInputs} />
}

function DictionaryField({ onChange, value }: { onChange?: (value: any) => void; value: any }): JSX.Element {
    const [entries, setEntries] = useState<[string, string][]>(Object.entries(value ?? {}))

    useEffect(() => {
        // NOTE: Filter out all empty entries as fetch will throw if passed in
        const val = Object.fromEntries(entries.filter(([key, val]) => key.trim() !== '' || val.trim() !== ''))
        onChange?.(val)
    }, [entries])

    return (
        <div className="space-y-2">
            {entries.map(([key, val], index) => (
                <div className="flex items-center gap-2" key={index}>
                    <LemonInput
                        value={key}
                        className="flex-1 min-w-60"
                        onChange={(key) => {
                            const newEntries = [...entries]
                            newEntries[index] = [key, newEntries[index][1]]
                            setEntries(newEntries)
                        }}
                        placeholder="Key"
                    />

                    <HogFunctionTemplateInput
                        className="flex-2 overflow-hidden"
                        value={val}
                        language="hogTemplate"
                        onChange={(val) => {
                            const newEntries = [...entries]
                            newEntries[index] = [newEntries[index][0], val ?? '']
                            setEntries(newEntries)
                        }}
                    />

                    <LemonButton
                        icon={<IconX />}
                        size="small"
                        onClick={() => {
                            const newEntries = [...entries]
                            newEntries.splice(index, 1)
                            setEntries(newEntries)
                        }}
                    />
                </div>
            ))}
            <LemonButton
                icon={<IconPlus />}
                size="small"
                type="secondary"
                onClick={() => {
                    setEntries([...entries, ['', '']])
                }}
            >
                Add entry
            </LemonButton>
        </div>
    )
}

export function HogFunctionInputRenderer({ value, onChange, schema, disabled }: HogFunctionInputProps): JSX.Element {
    switch (schema.type) {
        case 'string':
            return (
                <HogFunctionTemplateInput
                    language="hogTemplate"
                    value={value}
                    onChange={disabled ? () => {} : onChange}
                    className="ph-no-capture"
                />
            )
        case 'json':
            return <JsonConfigField value={value} onChange={onChange} className="ph-no-capture" />
        case 'choice':
            return (
                <LemonSelect
                    fullWidth
                    value={value}
                    className="ph-no-capture"
                    onChange={onChange}
                    options={schema.choices ?? []}
                    disabled={disabled}
                />
            )
        case 'dictionary':
            return <DictionaryField value={value} onChange={onChange} />

        case 'boolean':
            return <LemonSwitch checked={value} onChange={(checked) => onChange?.(checked)} disabled={disabled} />
        case 'integration':
            return <HogFunctionInputIntegration schema={schema} value={value} onChange={onChange} />
        case 'integration_field':
            return <HogFunctionInputIntegrationField schema={schema} value={value} onChange={onChange} />
        case 'email':
            return <EmailTemplateField schema={schema} />
        default:
            return (
                <strong className="text-danger">
                    Unknown field type "<code>{schema.type}</code>".
                </strong>
            )
    }
}

type HogFunctionInputSchemaControlsProps = {
    value: HogFunctionInputSchemaType
    onChange: (value: HogFunctionInputSchemaType | null) => void
    onDone: () => void
}

function HogFunctionInputSchemaControls({ value, onChange, onDone }: HogFunctionInputSchemaControlsProps): JSX.Element {
    const _onChange = (data: Partial<HogFunctionInputSchemaType> | null): void => {
        onChange(data ? { ...value, ...data } : null)
    }

    const [localVariableValue, setLocalVariableValue] = useState(value.key)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex-1 flex items-center gap-2 flex-wrap">
                <LemonSelect
                    size="small"
                    options={typeList.map((type) => ({
                        label: capitalizeFirstLetter(type),
                        value: type,
                    }))}
                    value={value.type}
                    className="w-30"
                    onChange={(type) => _onChange({ type })}
                />
                <LemonCheckbox
                    size="small"
                    checked={value.required}
                    onChange={(required) => _onChange({ required })}
                    label="Required"
                    bordered
                />
                <LemonCheckbox
                    size="small"
                    checked={value.secret}
                    onChange={(secret) => _onChange({ secret })}
                    label="Secret"
                    bordered
                />
                <div className="flex-1" />
                <LemonButton status="danger" icon={<IconTrash />} size="small" onClick={() => onChange(null)} />
                <LemonButton type="secondary" size="small" onClick={() => onDone()}>
                    Done
                </LemonButton>
            </div>
            <div className="flex-1 flex gap-2 flex-wrap">
                <LemonField.Pure label="Display label">
                    <LemonInput
                        className="min-w-60"
                        size="small"
                        value={value.label}
                        onChange={(label) => _onChange({ label })}
                        placeholder="Display label"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Input variable name">
                    <LemonInput
                        size="small"
                        value={localVariableValue}
                        // Special case - the component is keyed by this so the whole thing will re-mount on changes
                        // so we defer the change to blur
                        onChange={(key) => setLocalVariableValue(key)}
                        onBlur={() => _onChange({ key: localVariableValue })}
                        placeholder="Variable name"
                    />
                </LemonField.Pure>
            </div>

            <LemonField.Pure label="Description">
                <LemonTextArea
                    minRows={1}
                    value={value.description}
                    onChange={(description) => _onChange({ description })}
                    placeholder="Description"
                />
            </LemonField.Pure>
            {value.type === 'choice' && (
                <LemonField.Pure label="Choices">
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={value.choices?.map((choice) => choice.value)}
                        onChange={(choices) =>
                            _onChange({ choices: choices.map((value) => ({ label: value, value })) })
                        }
                        placeholder="Choices"
                    />
                </LemonField.Pure>
            )}

            {value.type === 'integration' && (
                <LemonField.Pure label="Integration kind">
                    <LemonSelect
                        value={value.integration}
                        onChange={(integration) => _onChange({ integration })}
                        options={[
                            { label: 'Slack', value: 'slack' },
                            { label: 'Salesforce', value: 'salesforce' },
                            { label: 'Hubspot', value: 'hubspot' },
                        ]}
                        placeholder="Choose kind"
                    />
                </LemonField.Pure>
            )}

            <LemonField.Pure label="Default value">
                <HogFunctionInputRenderer
                    schema={value}
                    value={value.default}
                    onChange={(val) => _onChange({ default: val })}
                />
            </LemonField.Pure>
        </div>
    )
}

export function HogFunctionInputWithSchema({ schema }: HogFunctionInputWithSchemaProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: schema.key })
    const { showSource, configuration } = useValues(hogFunctionConfigurationLogic)
    const { setConfigurationValue } = useActions(hogFunctionConfigurationLogic)
    const [editing, setEditing] = useState(showSource)

    const value = configuration.inputs?.[schema.key]

    const onSchemaChange = (newSchema: HogFunctionInputSchemaType | null): void => {
        let inputsSchema = configuration.inputs_schema || []
        if (!newSchema) {
            inputsSchema = inputsSchema.filter((s) => s.key !== schema.key)
        } else {
            const modifiedSchema = { ...schema, ...newSchema }
            inputsSchema = inputsSchema.map((s) => (s.key === schema.key ? modifiedSchema : s))
        }

        if (newSchema?.key) {
            setConfigurationValue(`inputs.${newSchema.key}`, value)
        }

        if (newSchema?.type && newSchema.type !== schema.type) {
            setConfigurationValue(`inputs.${schema.key}`, null)
        }

        setConfigurationValue('inputs_schema', inputsSchema)
    }

    useEffect(() => {
        if (!showSource) {
            setEditing(false)
        }
    }, [showSource])

    const supportsTemplating = ['string', 'json', 'dictionary', 'email'].includes(schema.type)

    return (
        <div
            className="group"
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
        >
            {!editing ? (
                <LemonField name={`inputs.${schema.key}`} help={schema.description}>
                    {({
                        value,
                        onChange,
                    }: {
                        value?: HogFunctionInputType
                        onChange: (val: HogFunctionInputType) => void
                    }) => {
                        return (
                            <>
                                <div className="flex items-center gap-2">
                                    <LemonLabel
                                        className={showSource ? 'cursor-grab' : ''}
                                        showOptional={!schema.required}
                                        {...attributes}
                                        {...listeners}
                                    >
                                        {schema.label || schema.key}
                                        {schema.secret ? (
                                            <Tooltip title="This input is marked as secret. It will be encrypted and not visible after saving.">
                                                <IconLock />
                                            </Tooltip>
                                        ) : undefined}
                                    </LemonLabel>
                                    {showSource && (
                                        <LemonTag type="muted" className="font-mono">
                                            inputs.{schema.key}
                                        </LemonTag>
                                    )}
                                    <div className="flex-1" />

                                    {supportsTemplating && (
                                        <LemonButton
                                            size="xsmall"
                                            to="https://posthog.com/docs/cdp/destinations#input-formatting"
                                            sideIcon={<IconInfo />}
                                            noPadding
                                            className=" opacity-0 group-hover:opacity-100 p-1 transition-opacity"
                                        >
                                            Supports templating
                                        </LemonButton>
                                    )}
                                    {showSource && (
                                        <LemonButton
                                            size="small"
                                            noPadding
                                            icon={<IconGear />}
                                            onClick={() => setEditing(true)}
                                        />
                                    )}
                                </div>
                                {value?.secret ? (
                                    <div className="border border-dashed rounded p-1 flex gap-2 items-center">
                                        <span className="flex-1 text-muted-alt italic p-1">
                                            This value is secret and is not displayed here.
                                        </span>
                                        <LemonButton
                                            onClick={() => {
                                                onChange({ value: undefined })
                                            }}
                                            size="small"
                                            type="secondary"
                                        >
                                            Edit
                                        </LemonButton>
                                    </div>
                                ) : (
                                    <HogFunctionInputRenderer
                                        schema={schema}
                                        value={value?.value}
                                        onChange={(val) => onChange({ value: val })}
                                    />
                                )}
                            </>
                        )
                    }}
                </LemonField>
            ) : (
                <div className="border rounded p-2 border-dashed space-y-4">
                    <HogFunctionInputSchemaControls
                        value={schema}
                        onChange={onSchemaChange}
                        onDone={() => setEditing(false)}
                    />
                </div>
            )}
        </div>
    )
}

export function HogFunctionInputs(): JSX.Element {
    const { showSource, configuration } = useValues(hogFunctionConfigurationLogic)
    const { setConfigurationValue } = useActions(hogFunctionConfigurationLogic)

    if (!configuration?.inputs_schema?.length) {
        return <span className="italic text-muted-alt">This function does not require any input variables.</span>
    }

    const inputSchemas = configuration.inputs_schema
    const inputSchemaIds = inputSchemas.map((schema) => schema.key)

    return (
        <>
            <DndContext
                collisionDetection={closestCenter}
                onDragEnd={({ active, over }) => {
                    if (over && active.id !== over.id) {
                        const oldIndex = inputSchemaIds.indexOf(active.id as string)
                        const newIndex = inputSchemaIds.indexOf(over.id as string)

                        setConfigurationValue('inputs_schema', arrayMove(inputSchemas, oldIndex, newIndex))
                    }
                }}
            >
                <SortableContext disabled={!showSource} items={inputSchemaIds} strategy={verticalListSortingStrategy}>
                    {configuration.inputs_schema?.map((schema) => {
                        return <HogFunctionInputWithSchema key={schema.key} schema={schema} />
                    })}
                </SortableContext>
            </DndContext>
        </>
    )
}
