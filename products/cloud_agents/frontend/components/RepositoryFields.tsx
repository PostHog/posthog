import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

/** The repository and the optional branch of a form. The form maps them to the `repositories` list. */
export function RepositoryFields({
    required = false,
    dataAttrPrefix,
}: {
    required?: boolean
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-3 @min-[30rem]:grid-cols-2">
                <LemonField name="repository" label="Repository" showOptional={!required}>
                    <LemonInput placeholder="owner/name" data-attr={`${dataAttrPrefix}-repository`} />
                </LemonField>
                <LemonField name="branch" label="Branch" showOptional>
                    <LemonInput placeholder="The default branch" data-attr={`${dataAttrPrefix}-branch`} />
                </LemonField>
            </div>
        </div>
    )
}
