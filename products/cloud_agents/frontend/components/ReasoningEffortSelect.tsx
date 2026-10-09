import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { CloudAgentReasoningEffortEnumApi } from '../generated/api.schemas'
import { REASONING_EFFORT_LABELS } from '../utils/runStatus'

/** A select of how much the model reasons. A model supports only some of the levels. */
export function ReasoningEffortSelect({
    value,
    onChange,
    emptyLabel = 'Default',
    'data-attr': dataAttr,
}: {
    value: CloudAgentReasoningEffortEnumApi | null
    onChange: (effort: CloudAgentReasoningEffortEnumApi | null) => void
    emptyLabel?: string
    'data-attr'?: string
}): JSX.Element {
    const options: LemonSelectOption<CloudAgentReasoningEffortEnumApi | null>[] = [
        { value: null, label: emptyLabel },
        ...Object.values(CloudAgentReasoningEffortEnumApi).map((effort) => ({
            value: effort,
            label: REASONING_EFFORT_LABELS[effort],
        })),
    ]
    return <LemonSelect fullWidth value={value} onChange={onChange} options={options} data-attr={dataAttr} />
}
