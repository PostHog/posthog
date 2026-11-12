import { useValues } from 'kea'
import { ChildFunctionProps } from 'kea-forms'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AddHeaderFieldButton } from './AddHeaderFieldButton'
import { COPY_HEADER_FIELDS, isHeaderFieldShown } from './emailHeaderFields'
import { EmailHeaderRow } from './EmailHeaderRow'
import { EMAIL_TYPE_SUPPORTED_FIELDS, emailTemplaterLogic } from './emailTemplaterLogic'
import { LiquidSupportedText } from './LiquidSupportedText'
import { OptionalHeaderFieldRow } from './OptionalHeaderFieldRow'

export function EmailRecipientFields(): JSX.Element {
    const { logicProps, visibleFields } = useValues(emailTemplaterLogic)
    const copyFields = COPY_HEADER_FIELDS.filter(({ key }) =>
        EMAIL_TYPE_SUPPORTED_FIELDS[logicProps.type].some((field) => field.key === key)
    )

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
                {copyFields
                    .filter(({ key }) => !isHeaderFieldShown(visibleFields, key))
                    .map((field) => (
                        <AddHeaderFieldButton key={field.key} field={field} />
                    ))}
            </EmailHeaderRow>
            {copyFields
                .filter(({ key }) => isHeaderFieldShown(visibleFields, key))
                .map((field) => (
                    <OptionalHeaderFieldRow key={field.key} field={field} />
                ))}
        </>
    )
}
