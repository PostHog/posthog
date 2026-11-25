import { IconCheckCircle, IconInfo, IconWarning, IconX } from '@posthog/icons'
import { Item, ItemContent, ItemMedia, ItemTitle, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { DiagnosticCheckResult, DiagnosticCheckStatus, DiagnosticReport } from './proxyLogic'

const CHECK_STATUS_ICONS: Record<DiagnosticCheckStatus, JSX.Element> = {
    passed: <IconCheckCircle className="text-success-foreground" />,
    warned: <IconWarning className="text-warning-foreground" />,
    failed: <IconX className="text-destructive-foreground" />,
    skipped: <IconInfo className="text-muted-foreground" />,
}

function QuillDiagnosticCheck({ check }: { check: DiagnosticCheckResult }): JSX.Element {
    return (
        <Item variant="outline" size="sm" className="items-start">
            <ItemMedia variant="icon">{CHECK_STATUS_ICONS[check.status]}</ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle>
                    <span>{check.name}</span>
                    <Text size="xs" variant="muted" render={<span className="capitalize" />}>
                        {`(${check.status})`}
                    </Text>
                </ItemTitle>
                <div className="flex flex-col gap-2 text-muted-foreground">
                    <LemonMarkdown className="text-xs">{check.detail}</LemonMarkdown>
                    {check.remediation && (
                        <div className="flex flex-col gap-2 border-t border-border pt-2">
                            <LemonMarkdown className="text-xs font-semibold">{check.remediation.summary}</LemonMarkdown>
                            {check.remediation.records.map((dnsRecord, i) => (
                                <CodeSnippet key={i} language={Language.HTTP}>
                                    {`${dnsRecord.name}\t${dnsRecord.type}\t${dnsRecord.value}`}
                                </CodeSnippet>
                            ))}
                        </div>
                    )}
                </div>
            </ItemContent>
        </Item>
    )
}

export function QuillProxyDiagnosticReport({ report }: { report: DiagnosticReport }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                {`Ran ${new Date(report.ran_at).toLocaleString()}`}
            </Text>
            {report.checks.map((check) => (
                <QuillDiagnosticCheck key={check.id} check={check} />
            ))}
        </div>
    )
}
