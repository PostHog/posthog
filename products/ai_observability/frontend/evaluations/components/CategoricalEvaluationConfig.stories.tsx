import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { EvaluationOutputConfig } from '../types'
import { CategoricalEvaluationConfig } from './CategoricalEvaluationConfig'

const meta: Meta<typeof CategoricalEvaluationConfig> = {
    title: 'Scenes-App/LLM observability/CategoricalEvaluationConfig',
    component: CategoricalEvaluationConfig,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof CategoricalEvaluationConfig>

function Template({
    narrow = false,
    initialConfig,
}: {
    narrow?: boolean
    initialConfig?: EvaluationOutputConfig
}): JSX.Element {
    const [config, setConfig] = useState<EvaluationOutputConfig>({
        options: [
            { key: 'resolved', label: 'Resolved' },
            { key: 'needs_follow_up', label: 'Needs follow-up' },
        ],
        selection_mode: 'multiple',
        allows_na: true,
        passing_rule: { categories: ['resolved'] },
        ...initialConfig,
    })
    return (
        <div className={narrow ? 'max-w-lg' : 'max-w-4xl'}>
            <CategoricalEvaluationConfig
                config={config}
                onChange={(patch) => setConfig((current) => ({ ...current, ...patch }))}
            />
        </div>
    )
}

export const Default: Story = { render: () => <Template /> }
export const Narrow: Story = { render: () => <Template narrow /> }
export const InvalidPassingRule: Story = {
    render: () => <Template narrow initialConfig={{ selection_mode: 'single', passing_rule: { categories: [] } }} />,
}
export const DuplicateKeys: Story = {
    render: () => (
        <Template
            narrow
            initialConfig={{
                options: [
                    { key: 'resolved', label: 'Resolved' },
                    { key: 'resolved', label: 'Needs follow-up' },
                ],
            }}
        />
    ),
}
