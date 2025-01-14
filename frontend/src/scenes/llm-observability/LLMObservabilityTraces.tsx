import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { llmObservabilityLogic } from './llmObservabilityLogic'

export function LLMObservabilityTraces(): JSX.Element {
    const { query } = useValues(llmObservabilityLogic)
    return <Query query={query} />
}
