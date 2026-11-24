import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { OptionalHeaderField } from './emailHeaderFields'
import { emailTemplaterLogic } from './emailTemplaterLogic'

/** A quiet button that reveals an optional field in its own row. */
export function AddHeaderFieldButton({ field }: { field: OptionalHeaderField }): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)
    const { revealAdvancedField } = useActions(emailTemplaterLogic)

    return (
        <LemonButton
            size="xsmall"
            type="tertiary"
            className="shrink-0"
            tooltip={field.info}
            onClick={() => {
                revealAdvancedField(field.key)
                posthog.capture('email header field added', { field: field.key, editor_type: logicProps.type })
            }}
            // pinned: data-attr values feed autocapture dashboards
            data-attr={`email-header-add-${field.key}`}
        >
            {field.label}
        </LemonButton>
    )
}
