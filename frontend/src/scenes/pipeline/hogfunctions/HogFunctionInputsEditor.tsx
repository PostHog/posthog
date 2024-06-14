import { IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'kea-forms'

import { HogFunctionInputSchemaType } from '~/types'

const typeList = ['string', 'boolean', 'dictionary', 'choice', 'json'] as const

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
