import { Card, Row, Select } from 'antd'
import { IconOpenInNew } from 'lib/components/icons'
import React, { useState } from 'react'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { Experiment, MultivariateFlagVariant } from '~/types'
import { CodeLanguageSelect } from './Experiment'
import { CaretDownOutlined } from '@ant-design/icons'

interface ExperimentImplementationDetailsProps {
    experiment: Partial<Experiment> | null
}

export function ExperimentImplementationDetails({ experiment }: ExperimentImplementationDetailsProps): JSX.Element {
    const [currentVariant, setCurrentVariant] = useState('control')

    return (
        <Card
            title={<span className="card-secondary">Feature flag usage and implementation</span>}
            className="experiment-implementation-details"
        >
            <Row justify="space-between" className="mb-2">
                <div>
                    <span className="mr-2">Variant group</span>
                    <Select onChange={setCurrentVariant} defaultValue={'control'} suffixIcon={<CaretDownOutlined />}>
                        {experiment?.parameters?.feature_flag_variants?.map(
                            (variant: MultivariateFlagVariant, idx: number) => (
                                <Select.Option key={idx} value={variant.key}>
                                    {variant.key}
                                </Select.Option>
                            )
                        )}
                    </Select>
                </div>
                <div>
                    <CodeLanguageSelect />
                </div>
            </Row>
            <b>Implement your experiment in code</b>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.getFeatureFlag('${experiment?.feature_flag_key ?? ''}') === '${currentVariant}') {
    // where '${currentVariant}' is the variant, run your code here
}`}
            </CodeSnippet>
            <b>Test that it works</b>
            <CodeSnippet language={Language.JavaScript}>
                {`posthog.feature_flags.override({'${experiment?.feature_flag_key}': '${currentVariant}'})`}
            </CodeSnippet>
            <a target="_blank" rel="noopener noreferrer" href="https://posthog.com/docs/user-guides/feature-flags">
                <Row align="middle">
                    Experiment implementation guide
                    <IconOpenInNew className="ml-2" />
                </Row>
            </a>
        </Card>
    )
}
