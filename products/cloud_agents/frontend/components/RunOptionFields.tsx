import { LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { IDLE_MINUTES_DEFAULT, IDLE_MINUTES_MAX, IDLE_MINUTES_MIN } from '../utils/runOptions'
import { ReasoningEffortSelect } from './ReasoningEffortSelect'

/** The reasoning effort, the idle time and the output schema. Every form that sets run options shows the same three fields. */
export function RunOptionFields({
    emptyLabel,
    dataAttrPrefix,
}: {
    emptyLabel: string
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <>
            <div className="@container">
                <div className="grid grid-cols-1 gap-3 @min-[30rem]:grid-cols-2">
                    <LemonField
                        name="reasoning_effort"
                        label="Reasoning effort"
                        help="How much the model reasons before it answers. A model supports only some levels."
                    >
                        {({ value, onChange }) => (
                            <ReasoningEffortSelect
                                value={value}
                                onChange={onChange}
                                emptyLabel={emptyLabel}
                                data-attr={`${dataAttrPrefix}-reasoning-effort`}
                            />
                        )}
                    </LemonField>
                    <LemonField
                        name="idle_minutes"
                        label="Idle time in minutes"
                        showOptional
                        help={`How long the sandbox waits with no activity before it stops. A shorter wait costs less compute. From ${IDLE_MINUTES_MIN} to ${IDLE_MINUTES_MAX}, ${IDLE_MINUTES_DEFAULT} by default.`}
                    >
                        {({ value, onChange }) => (
                            <LemonInput
                                type="number"
                                min={IDLE_MINUTES_MIN}
                                max={IDLE_MINUTES_MAX}
                                step={1}
                                placeholder={String(IDLE_MINUTES_DEFAULT)}
                                value={value ?? undefined}
                                onChange={(minutes) => onChange(minutes ?? null)}
                                data-attr={`${dataAttrPrefix}-idle-minutes`}
                            />
                        )}
                    </LemonField>
                </div>
            </div>
            <LemonField
                name="output_schema"
                label="Output schema"
                showOptional
                help="A JSON Schema object. The agent returns a result that matches it, and the run shows it as the output."
            >
                <LemonTextArea
                    minRows={4}
                    className="font-mono text-xs"
                    placeholder='{"type": "object", "properties": {"summary": {"type": "string"}}}'
                    data-attr={`${dataAttrPrefix}-output-schema`}
                />
            </LemonField>
        </>
    )
}
