import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'kea-forms'
import { useEffect, useState } from 'react'

import { HogFunctionInputSchemaType } from '~/types'

const typeList = ['string', 'boolean', 'dictionary', 'choice', 'json'] as const

export type HogFunctionInputsEditorProps = {
    value?: HogFunctionInputSchemaType[]
    onChange?: (value: HogFunctionInputSchemaType[]) => void
}

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
                    <div className="flex items-center gap-2 border rounded p-1" key={index}>
                        <div className="flex-1 flex items-center gap-2">
                            <LemonSelect
                                size="small"
                                options={typeList.map((type) => ({
                                    label: capitalizeFirstLetter(type),
                                    value: type,
                                }))}
                                value={input.type}
                                onChange={(type) => _onChange({ type })}
                            />

                            <LemonInput
                                size="small"
                                value={input.name}
                                onChange={(name) => _onChange({ name })}
                                placeholder="Variable name"
                            />
                            <LemonInput
                                size="small"
                                value={input.label}
                                onChange={(label) => _onChange({ label })}
                                placeholder="Variable label"
                            />
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
                            { type: 'string', name: `input_${inputs.length + 1}`, label: '', required: false },
                        ])
                    }}
                >
                    Add input variable
                </LemonButton>
            </div>
        </div>
    )
}
