import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { EvaluationOutputConfig } from '../types'
import { NumericEvaluationConfig } from './NumericEvaluationConfig'

const meta: Meta<typeof NumericEvaluationConfig> = {
    title: 'Scenes-App/LLM observability/NumericEvaluationConfig',
    component: NumericEvaluationConfig,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof NumericEvaluationConfig>

function Template({ narrow = false, systemOne = false }: { narrow?: boolean; systemOne?: boolean }): JSX.Element {
    const [config, setConfig] = useState<EvaluationOutputConfig>({
        min: 0,
        max: 10,
        step: 0.5,
        allows_na: true,
        passing_rule: { operator: 'gte', threshold: 7 },
        ...(systemOne
            ? { score_levels: ['Does not meet the criteria', 'Partly meets the criteria', 'Fully meets the criteria'] }
            : {}),
    })
    return (
        <div className={narrow ? 'max-w-lg' : 'max-w-4xl'}>
            <NumericEvaluationConfig
                config={config}
                requiresScoreLevels={systemOne}
                onChange={(patch) => setConfig((current) => ({ ...current, ...patch }))}
            />
        </div>
    )
}

export const Default: Story = { render: () => <Template /> }
export const Narrow: Story = { render: () => <Template narrow /> }
export const SystemOne: Story = { render: () => <Template systemOne narrow /> }
