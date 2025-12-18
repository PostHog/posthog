import { LemonButton, LemonDivider, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import type { Experiment } from '~/types'

type ExperimentDetailsPanelProps = {
    experiment: Experiment
    experimentErrors: Record<string, string>
    onChange: (field: string, value: string) => void
    onValidate: (field: 'name') => void
    onNext: () => void
}

export function ExperimentDetailsPanel({
    experiment,
    experimentErrors,
    onChange,
    onValidate,
    onNext,
}: ExperimentDetailsPanelProps): JSX.Element {
    return (
        <div className="space-y-4">
            <div className="text-sm text-muted">
                Give your experiment a name and describe what you're trying to learn.
            </div>

            <div>
                <label className="block text-sm font-medium text-default mb-2">Name</label>
                <LemonInput
                    value={experiment.name}
                    onChange={(value) => onChange('name', value)}
                    onBlur={() => onValidate('name')}
                    placeholder="e.g., Checkout button color test"
                    data-attr="experiment-name"
                    status={experimentErrors.name ? 'danger' : undefined}
                    fullWidth
                />
                {experimentErrors.name && typeof experimentErrors.name === 'string' && (
                    <div className="text-danger flex items-center gap-1 text-sm mt-1">
                        <IconErrorOutline className="text-xl shrink-0" /> {experimentErrors.name}
                    </div>
                )}
            </div>

            <div>
                <label className="block text-sm font-medium text-default mb-2">Hypothesis</label>
                <LemonTextArea
                    value={experiment.description}
                    onChange={(value) => onChange('description', value)}
                    placeholder="The goal of this experiment is ..."
                    data-attr="experiment-hypothesis"
                    minRows={3}
                />
                <div className="text-xs text-muted mt-1">Describe your experiment in a few sentences.</div>
            </div>

            <LemonDivider />
            <div className="flex justify-end pt-2">
                <LemonButton type="primary" size="small" onClick={onNext}>
                    Next
                </LemonButton>
            </div>
        </div>
    )
}
