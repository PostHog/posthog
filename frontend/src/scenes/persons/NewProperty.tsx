import { useState } from 'react'

import { LemonInput, LemonLabel, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

interface NewPropertyInterface {
    creating: boolean
    propertyType: 'string' | 'boolean'
    key?: string | null
    value?: string | number
}

export interface NewPropertyProps {
    onSave: (key: string, newValue?: string | number) => void
}

export function NewProperty({ onSave }: NewPropertyProps): JSX.Element {
    const initialState = { creating: false, propertyType: 'string', value: '' } as NewPropertyInterface
    const [state, setState] = useState(initialState)

    const saveProperty = (): void => {
        if (state.key && state.value !== undefined) {
            onSave(state.key, state.value)
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
                title="Add new property"
                footer={
                    <LemonButton
                        disabledReason={(!state.key || state.value === undefined) && 'Set a key and a value'}
                        type="secondary"
                        onClick={saveProperty}
                    >
                        Save
                    </LemonButton>
                }
            >
                <div className="deprecated-space-y-2">
                    <div>
                        <LemonLabel>Key</LemonLabel>
                        <LemonInput
                            id="propertyKey"
                            autoFocus
                            placeholder="try email, first_name, is_verified, membership_level, total_revenue"
                            onChange={(key) => setState({ ...state, key: key })}
                            autoComplete="off"
                            autoCapitalize="off"
                        />
                    </div>
                    <div>
                        <LemonLabel>Type of Property</LemonLabel>
                        <LemonSegmentedButton
                            onChange={(value: 'string' | 'boolean') =>
                                setState({
                                    ...state,
                                    propertyType: value,
                                    value: value === 'string' ? '' : 'true',
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
                            fullWidth
                        />
                    </div>
                    <div>
                        <LemonLabel>Value</LemonLabel>
                        {state.propertyType === 'boolean' ? (
                            <LemonSegmentedButton
                                onChange={(value) =>
                                    setState({
                                        ...state,
                                        value: value,
                                    })
                                }
                                fullWidth
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
                                size="small"
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
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
