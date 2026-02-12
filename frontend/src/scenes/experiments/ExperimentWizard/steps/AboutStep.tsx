import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { slugify } from 'lib/utils'

import { experimentWizardLogic } from '../experimentWizardLogic'

export function AboutStep(): JSX.Element {
    const { experiment } = useValues(experimentWizardLogic)
    const { setExperimentValue } = useActions(experimentWizardLogic)

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold">What are we testing?</h3>
            </div>

            <LemonField.Pure label="Experiment name">
                <LemonInput
                    placeholder="e.g., New checkout flow test"
                    value={experiment.name}
                    onChange={(value) => {
                        setExperimentValue('name', value)
                        if (!experiment.feature_flag_key || experiment.feature_flag_key === slugify(experiment.name)) {
                            setExperimentValue('feature_flag_key', slugify(value))
                        }
                    }}
                    data-attr="experiment-wizard-name"
                />
            </LemonField.Pure>

            <LemonField.Pure label="Hypothesis" info="Describe what you expect to happen and why.">
                <LemonTextArea
                    placeholder="We believe that ... will result in ... because ..."
                    value={experiment.description ?? ''}
                    onChange={(value) => setExperimentValue('description', value)}
                    data-attr="experiment-wizard-hypothesis"
                    minRows={3}
                />
            </LemonField.Pure>

            <LemonField.Pure label="Feature flag key">
                <div className="flex items-center gap-2">
                    <LemonInput
                        placeholder="e.g., new-checkout-flow-test"
                        value={experiment.feature_flag_key ?? ''}
                        onChange={(value) => setExperimentValue('feature_flag_key', value)}
                        data-attr="experiment-wizard-flag-key"
                        fullWidth
                    />
                </div>
            </LemonField.Pure>
        </div>
    )
}
