import { Heading, Item, ItemContent, ItemDescription, ItemTitle, Separator, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function QuillSetupWizardBanner({
    integrationName,
    wizardCommand,
}: {
    integrationName: string
    wizardCommand: string
}): JSX.Element {
    return (
        <>
            <Heading size="sm" render={<h3 className="m-0" />}>
                Automated installation
            </Heading>
            <Item tone="info">
                <ItemContent className="gap-2">
                    <ItemTitle>AI setup wizard</ItemTitle>
                    <ItemDescription>Try using the AI setup wizard to automatically install PostHog.</ItemDescription>
                    <ItemDescription>
                        Run the following command from the root of your {integrationName} project.
                    </ItemDescription>
                    <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
                </ItemContent>
            </Item>
            <div className="flex items-center gap-2">
                <Separator className="flex-1" />
                <Text size="xs" variant="muted" render={<span />}>
                    OR
                </Text>
                <Separator className="flex-1" />
            </div>
            <Heading size="sm" render={<h3 className="m-0" />}>
                Manual installation
            </Heading>
        </>
    )
}
