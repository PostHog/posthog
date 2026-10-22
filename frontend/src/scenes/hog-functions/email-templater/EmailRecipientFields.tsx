import { useValues } from 'kea'
import { ChildFunctionProps } from 'kea-forms'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AddHeaderFieldButton } from './AddHeaderFieldButton'
import { COPY_HEADER_FIELDS, isHeaderFieldShown } from './emailHeaderFields'
import { EmailHeaderRow } from './EmailHeaderRow'
import { emailTemplaterLogic } from './emailTemplaterLogic'
import { LiquidSupportedText } from './LiquidSupportedText'
import { OptionalHeaderFieldRow } from './OptionalHeaderFieldRow'

export function EmailRecipientFields(): JSX.Element {
    const { logicProps, visibleFields } = useValues(emailTemplaterLogic)

    return (
        <>
            <EmailHeaderRow label="To" error={logicProps.fieldErrors?.to}>
                <LemonField name="to" className="flex-1 min-w-0" renderError={() => null}>
                    {/* `to` is { email, name }, and only the address is edited here */}
                    {({ value, onChange }: ChildFunctionProps) => (
                        <LiquidSupportedText
                            value={value?.email}
                            onChange={(email) => onChange({ ...value, email })}
                            globals={logicProps.variables}
                        />
                    )}
                </LemonField>
                {COPY_HEADER_FIELDS.filter(({ key }) => !isHeaderFieldShown(visibleFields, key)).map((field) => (
                    <AddHeaderFieldButton key={field.key} field={field} />
                ))}
            </EmailHeaderRow>
            {COPY_HEADER_FIELDS.filter(({ key }) => isHeaderFieldShown(visibleFields, key)).map((field) => (
                <OptionalHeaderFieldRow key={field.key} field={field} />
            ))}
        </>
    )
}
