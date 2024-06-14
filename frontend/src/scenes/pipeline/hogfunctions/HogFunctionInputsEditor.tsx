import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'kea-forms'
import { useEffect, useState } from 'react'

import { HogFunctionInputSchemaType } from '~/types'

const typeList = ['string', 'boolean', 'dictionary', 'choice', 'json'] as const

export function HogFunctionInputsEditor({ value, onChange }: HogFunctionInputsEditorProps): JSX.Element {
    const [inputs, setInputs] = useState<HogFunctionInputSchemaType[]>(value ?? [])

    useEffect(() => {
        onChange?.(inputs)
    }, [inputs])

    return (
        <div className="space-y-2">
            {inputs.map((input, index) => {
                const _onChange = (data: Partial<HogFunctionInputSchemaType>): void => {
                    setInputs((inputs) => {
                        const newInputs = [...inputs]
                        newInputs[index] = { ...newInputs[index], ...data }
                        return newInputs
                    })
                }

                return (
                    <div className="flex items-center gap-2 flex-wrap border rounded p-1" key={index}>
                        <div className="flex-1 flex items-center gap-2 flex-wrap">
                            <LemonInput
                                size="small"
                                value={input.key}
                                onChange={(key) => _onChange({ key })}
                                placeholder="Variable name"
                            />
                            <LemonSelect
                                size="small"
                                options={typeList.map((type) => ({
                                    label: capitalizeFirstLetter(type),
                                    value: type,
                                }))}
                                value={input.type}
                                className="w-30"
                                onChange={(type) => _onChange({ type })}
                            />

                            <LemonInput
                                className="flex-1 min-w-30"
                                size="small"
                                value={input.label}
                                onChange={(label) => _onChange({ label })}
                                placeholder="Display label"
                            />
                            <LemonCheckbox
                                size="small"
                                checked={input.required}
                                onChange={(required) => _onChange({ required })}
                                label="Required"
                                bordered
                            />
                            <LemonCheckbox
                                size="small"
                                checked={input.secret}
                                onChange={(secret) => _onChange({ secret })}
                                label="Secret"
                                bordered
                            />
                            {input.type === 'choice' && (
                                <LemonInputSelect
                                    mode="multiple"
                                    allowCustomValues
                                    value={input.choices?.map((choice) => choice.value)}
                                    onChange={(choices) =>
                                        _onChange({ choices: choices.map((value) => ({ label: value, value })) })
                                    }
                                    placeholder="Choices"
                                />
                            )}
                        </div>
                        <LemonButton
                            icon={<IconX />}
                            size="small"
                            onClick={() => {
                                const newInputs = [...inputs]
                                newInputs.splice(index, 1)
                                setInputs(newInputs)
                            }}
                        />
                    </div>
                )
            })}

            <div className="flex">
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    type="secondary"
                    onClick={() => {
                        setInputs([
                            ...inputs,
                            { type: 'string', key: `input_${inputs.length + 1}`, label: '', required: false },
                        ])
                    }}
                >
                    Add input variable
                </LemonButton>
            </div>
        </div>
    )
}

export type HogFunctionInputSchemaProps = {
    value: HogFunctionInputSchemaType
    onChange: (value: HogFunctionInputSchemaType | null) => void
}

export function HogFunctionInputSchema({ value, onChange }: HogFunctionInputSchemaProps): JSX.Element {
    const _onChange = (data: Partial<HogFunctionInputSchemaType> | null): void => {
        onChange(data ? { ...value, ...data } : null)
    }

    return (
        <div className="flex items-center gap-2 flex-wrap border border-dashed rounded p-1">
            <div className="flex-1 flex items-center gap-2 flex-wrap">
                <LemonInput
                    size="small"
                    value={value.key}
                    onChange={(key) => _onChange({ key })}
                    placeholder="Variable name"
                />
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

                <LemonInput
                    className="flex-1 min-w-30"
                    size="small"
                    value={value.label}
                    onChange={(label) => _onChange({ label })}
                    placeholder="Display label"
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
                {value.type === 'choice' && (
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={value.choices?.map((choice) => choice.value)}
                        onChange={(choices) =>
                            _onChange({ choices: choices.map((value) => ({ label: value, value })) })
                        }
                        placeholder="Choices"
                    />
                )}
            </div>
            <LemonButton icon={<IconX />} size="small" onClick={() => onChange(null)} />
        </div>
    )
}
