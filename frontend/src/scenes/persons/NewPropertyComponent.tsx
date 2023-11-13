import { useState } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'
import { Field } from 'kea-forms'

interface NewPropertyInterface {
    creating: boolean
    propertyType: 'string' | 'boolean'
    key?: string | null
    value?: string | number | boolean | null
}

export interface NewPropertyComponentProps {
    editProperty: (key: string, newValue?: string | number | boolean | null) => void
}

export function NewPropertyComponent({ editProperty }: NewPropertyComponentProps): JSX.Element {
    const initialState = { creating: false, propertyType: 'string' } as NewPropertyInterface
    const [state, setState] = useState(initialState)

    const saveProperty = (): void => {
        if (state.key && state.value !== undefined) {
            editProperty(state.key, state.value)
            setState(initialState)
        }
    }

    return (
        <>
            <LemonButton
                data-attr="add-prop-button"
                onClick={() => setState({ ...state, creating: true })}
                type="primary"
            >
                New property
            </LemonButton>
            <LemonModal
                isOpen={state.creating}
                onClose={() => setState(initialState)}
                title="Adding new property"
                footer={
                    <LemonButton
                        disabledReason={(!state.key || state.value === undefined) && 'This is a reason'}
                        type="secondary"
                        onClick={saveProperty}
                    >
                        Save
                    </LemonButton>
                }
            >
                <Field name="key" label="Key">
                    <LemonInput
                        id="propertyKey"
                        autoFocus
                        placeholder="try email, first_name, is_verified, membership_level, total_revenue"
                        onChange={(key) => setState({ ...state, key: key })}
                        autoComplete="off"
                        autoCapitalize="off"
                    />
                </Field>
                <Field name="typeOfProperty" label="Type of Property">
                    <LemonSegmentedButton
                        onChange={(value: 'string' | 'boolean') =>
                            setState({
                                ...state,
                                propertyType: value,
                                value: value === 'string' ? undefined : 'true',
                            })
                        }
                        value={state.propertyType}
                        options={[
                            {
                                value: 'string',
                                label: 'Text or Number',
                            },
                            {
                                value: 'boolean',
                                label: 'Boolean or Null',
                            },
                        ]}
                    />
                </Field>

                <Field name="value" label="Value">
                    {state.propertyType === 'boolean' ? (
                        <LemonSegmentedButton
                            onChange={(value) =>
                                setState({
                                    ...state,
                                    value: value,
                                })
                            }
                            value={state.value}
                            options={[
                                {
                                    value: 'true',
                                    label: 'True',
                                },
                                {
                                    value: 'false',
                                    label: 'False',
                                },
                                {
                                    value: 'null',
                                    label: 'Null',
                                },
                            ]}
                        />
                    ) : (
                        <LemonInput
                            id="propertyValue"
                            placeholder="try email@example.com, gold, 1"
                            onChange={(value) => setState({ ...state, value: value })}
                            onKeyDown={(e) => e.key === 'Enter' && saveProperty()}
                            autoComplete="off"
                            autoCapitalize="off"
                        />
                    )}
                </Field>
            </LemonModal>
        </>
    )
}
