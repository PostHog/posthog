import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { biMetricParametersLogic } from './biMetricParametersLogic'

export function BIMetricParametersModal({ tabId }: { tabId: string }): JSX.Element {
    const { source, parameters, parameterErrors, applyDisabledReason } = useValues(biMetricParametersLogic({ tabId }))
    const { close, changeParameter, apply } = useActions(biMetricParametersLogic({ tabId }))

    return (
        <LemonModal
            title="Edit metric parameters"
            isOpen={!!source}
            onClose={close}
            footer={
                <>
                    <LemonButton onClick={close}>Cancel</LemonButton>
                    <LemonButton type="primary" onClick={apply} disabledReason={applyDisabledReason}>
                        Apply
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4 ph-no-capture">
                <p>Changes apply to this worksheet. The catalog definition stays the same.</p>
                {parameters.map(({ name, type, value }) => (
                    <div key={name} className="space-y-1">
                        {type === 'boolean' ? (
                            <LemonCheckbox
                                label={name}
                                checked={value === true}
                                onChange={(value) => changeParameter(name, value)}
                            />
                        ) : (
                            <>
                                <LemonLabel htmlFor={`bi-parameter-${name}`}>{name}</LemonLabel>
                                <LemonInput
                                    id={`bi-parameter-${name}`}
                                    value={String(value)}
                                    onChange={(value) => changeParameter(name, value)}
                                    status={parameterErrors[name] ? 'danger' : undefined}
                                />
                                {parameterErrors[name] && (
                                    <div className="text-danger" role="alert">
                                        {parameterErrors[name]}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                ))}
            </div>
        </LemonModal>
    )
}
