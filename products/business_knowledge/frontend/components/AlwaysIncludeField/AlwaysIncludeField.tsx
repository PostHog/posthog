import { LemonCheckbox } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

export function AlwaysIncludeField(): JSX.Element {
    return (
        <LemonField
            name="always_include"
            info="When on, this source's content is injected into every reply as general guidance (tone, policies, company direction) — not just when it matches the question. Still gated by the same safety checks as search."
        >
            {({ value, onChange }) => (
                <LemonCheckbox
                    checked={!!value}
                    onChange={onChange}
                    label="Always include in replies"
                    bordered
                    fullWidth
                />
            )}
        </LemonField>
    )
}
