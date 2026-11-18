import { useId } from 'react'

import { Button, Checkbox, Field, FieldLabel, Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function QuillCSPReportingSettings({
    parameterOptions,
    reportUrl,
    restrictedReason,
}: {
    parameterOptions: { label: string; checked: boolean; onChange: (checked: boolean) => void }[]
    reportUrl: string
    restrictedReason: string | null
}): JSX.Element {
    const idPrefix = useId()

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    A CSP is an instruction to the browser on what assets are allowed to be loaded and what domains your
                    site can send information to. It's a very powerful security mechanism, that can be super tricky to
                    configure.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    CSP Reporting lets you track your CSP by sending reports to PostHog when a CSP violation occurs.
                    This helps you see when CSP misconfiguration, web site changes, or security flaws are causing
                    problems.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    PostHog supports both the{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-uri"
                                target="_blank"
                            />
                        }
                    >
                        report-uri
                    </Button>{' '}
                    and{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-to"
                                target="_blank"
                            />
                        }
                    >
                        report-to
                    </Button>{' '}
                    directives, converting violations into an event. Letting you track and alert on them just like any
                    other event.
                </Text>
            </div>
            <div className="flex flex-col gap-2">
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            We accept some additional parameters on the report URL. These require that you add
                            information when adding the URL to your pages.{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to="https://posthog.com/docs/csp-tracking" />}
                            >
                                See our docs for some examples.
                            </Button>
                        </ItemDescription>
                    </ItemContent>
                </Item>
                {parameterOptions.map((option, index) => {
                    const checkboxId = `${idPrefix}-${index}`

                    return (
                        <Field key={option.label} orientation="horizontal">
                            <Checkbox
                                id={checkboxId}
                                checked={option.checked}
                                onCheckedChange={(checked: boolean) => option.onChange(checked)}
                                disabledReason={restrictedReason}
                            />
                            <FieldLabel htmlFor={checkboxId}>{option.label}</FieldLabel>
                        </Field>
                    )
                })}
            </div>
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Set this URL for both the report-to and report-uri endpoints
                </Text>
                <CodeSnippet language={Language.Text} wrap={true}>
                    {reportUrl}
                </CodeSnippet>
            </div>
        </div>
    )
}
