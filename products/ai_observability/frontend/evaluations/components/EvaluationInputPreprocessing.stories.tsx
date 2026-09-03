import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { EvaluationInputTransformation } from '../types'
import { EvaluationInputPreprocessing } from './EvaluationInputPreprocessing'
import type { EvaluationInputPreprocessingProps } from './EvaluationInputPreprocessing'

const meta: Meta<typeof EvaluationInputPreprocessing> = {
    title: 'Products/AI observability/Evaluations/Input preprocessing',
    component: EvaluationInputPreprocessing,
}

export default meta
type Story = StoryObj<typeof EvaluationInputPreprocessing>

function InputPreprocessingStory(props: Pick<EvaluationInputPreprocessingProps, 'transformations'>): JSX.Element {
    const [transformations, setTransformations] = useState(props.transformations)

    return (
        <div className="@container/main-content w-[800px] max-w-full">
            <EvaluationInputPreprocessing
                transformations={transformations}
                onAdd={() => setTransformations([...transformations, { pattern: '', replacement: '' }])}
                onUpdate={(index, patch) =>
                    setTransformations(
                        transformations.map((transformation, transformationIndex) =>
                            transformationIndex === index ? { ...transformation, ...patch } : transformation
                        )
                    )
                }
                onRemove={(index) =>
                    setTransformations(
                        transformations.filter((_, transformationIndex) => transformationIndex !== index)
                    )
                }
                onMove={(index, direction) => {
                    const next = [...transformations]
                    const destination = direction === 'up' ? index - 1 : index + 1
                    ;[next[index], next[destination]] = [next[destination], next[index]]
                    setTransformations(next)
                }}
            />
        </div>
    )
}

export const WithRules: Story = {
    render: () => (
        <InputPreprocessingStory
            transformations={[
                { pattern: '(?s)<onboarding_brief>.*?</onboarding_brief>', replacement: '' },
                { pattern: 'sk-[A-Za-z0-9]+', replacement: '[API key removed]' },
            ]}
        />
    ),
}

export const Empty: Story = {
    render: () => <InputPreprocessingStory transformations={[] as EvaluationInputTransformation[]} />,
}
