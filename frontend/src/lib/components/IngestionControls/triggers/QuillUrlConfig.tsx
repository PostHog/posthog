import { useValues } from 'kea'
import { ComponentProps, ReactNode, useId } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Field, FieldLabel, Heading, Input, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { ingestionControlsLogic } from '../ingestionControlsLogic'
import { QuillUrlConfigForm } from './QuillUrlConfigForm'
import { QuillUrlConfigRow } from './QuillUrlConfigRow'
import { UrlConfig } from './UrlConfig'

export function QuillUrlConfig({
    logic,
    logicProps,
    formKey,
    validationWarning,
    aiRegexHelper,
    title,
    description,
    checkUrl,
    checkUrlResults,
    setCheckUrl,
    titleBadge,
    ...props
}: Omit<ComponentProps<typeof UrlConfig>, 'addUrl'> & { aiRegexHelper?: ReactNode }): JSX.Element {
    const { logicKey } = useValues(ingestionControlsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const checkUrlId = useId()

    const matchesAnyPattern = Object.values(checkUrlResults).some(Boolean)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                    {title}
                    {titleBadge}
                </Heading>
                <Button
                    onClick={props.onAdd}
                    variant="outline"
                    data-attr={`${logicKey}-add-url`}
                    disabledReason={restrictedReason}
                >
                    <IconPlus />
                    Add
                </Button>
            </div>
            <Text size="xs" render={<p className="m-0" />}>
                {description}
            </Text>

            {props.isAddFormVisible && (
                <QuillUrlConfigForm
                    logic={logic}
                    logicProps={logicProps}
                    formKey={formKey}
                    aiRegexHelper={aiRegexHelper}
                    validationWarning={validationWarning}
                    onCancel={props.onCancel}
                    isSubmitting={props.isSubmitting}
                />
            )}

            {!props.isAddFormVisible && props.config && props.config.length > 0 && (
                <Field className="rounded-md border border-border p-3">
                    <FieldLabel htmlFor={checkUrlId}>Test a full URL against these patterns:</FieldLabel>
                    <Input
                        id={checkUrlId}
                        value={checkUrl}
                        onChange={(event) => setCheckUrl(event.target.value)}
                        placeholder="e.g., https://example.com/checkout?step=2"
                        data-attr="url-check-input"
                    />
                    {checkUrl && (
                        <Text
                            size="xs"
                            className={matchesAnyPattern ? 'text-success-foreground' : 'text-destructive-foreground'}
                            render={<p className="m-0" />}
                        >
                            {matchesAnyPattern
                                ? '✓ This URL matches at least one pattern'
                                : "✗ This URL doesn't match any patterns. Patterns match the full URL, so a path on its own never matches."}
                        </Text>
                    )}
                </Field>
            )}
            {props.config?.map((trigger, index) => (
                <QuillUrlConfigRow
                    logic={logic}
                    logicProps={logicProps}
                    formKey={formKey}
                    aiRegexHelper={aiRegexHelper}
                    validationWarning={validationWarning}
                    key={`${trigger.url}-${trigger.matching}`}
                    trigger={trigger}
                    index={index}
                    editIndex={props.editIndex}
                    onEdit={props.onEdit}
                    onRemove={props.onRemove}
                    checkUrlResult={checkUrlResults[index]}
                />
            ))}
        </div>
    )
}
