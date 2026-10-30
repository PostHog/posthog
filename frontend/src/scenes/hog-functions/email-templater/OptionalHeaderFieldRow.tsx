import { useActions, useValues } from 'kea'
import { ChildFunctionProps } from 'kea-forms'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { OptionalHeaderField } from './emailHeaderFields'
import { EmailHeaderRow } from './EmailHeaderRow'
import { emailTemplaterLogic } from './emailTemplaterLogic'
import { LiquidSupportedText } from './LiquidSupportedText'

/** A revealed optional field. Removing it clears the value and hides the row again. */
export function OptionalHeaderFieldRow({ field }: { field: OptionalHeaderField }): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)
    const { hideAdvancedField } = useActions(emailTemplaterLogic)

    return (
        <LemonField name={field.key} renderError={() => null}>
            {({ value, onChange }: ChildFunctionProps) => (
                <EmailHeaderRow label={field.label} info={field.info}>
                    <LiquidSupportedText value={value} onChange={onChange} globals={logicProps.variables} />
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconX />}
                        onClick={() => {
                            onChange('')
                            hideAdvancedField(field.key)
                        }}
                        tooltip={`Remove ${field.label}`}
                    />
                </EmailHeaderRow>
            )}
        </LemonField>
    )
}
