import { IconRefresh } from '@posthog/icons'
import { Button, Card, CardContent, Heading, Text } from '@posthog/quill'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { Region } from '~/types'

function TeamVariableCard({
    title,
    className,
    children,
}: {
    title: string
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <Card size="sm" className={className}>
            <CardContent className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    {title}
                </Heading>
                {children}
            </CardContent>
        </Card>
    )
}

export function QuillTeamVariables({
    apiToken,
    projectId,
    region,
    isTokenResetAvailable,
    restrictedReason,
    onResetToken,
}: {
    apiToken: string
    projectId: string
    region: Region | null | undefined
    isTokenResetAvailable: boolean
    restrictedReason: string | null
    onResetToken: () => void
}): JSX.Element {
    return (
        <div className="flex max-w-200 flex-col gap-4">
            <TeamVariableCard title="Project token">
                <CodeSnippet
                    compact
                    thing="project token"
                    actions={
                        isTokenResetAvailable ? (
                            <Button
                                size="icon-sm"
                                aria-label="Reset token"
                                tooltip="Reset token"
                                disabledReason={restrictedReason}
                                onClick={onResetToken}
                            >
                                <IconRefresh />
                            </Button>
                        ) : undefined
                    }
                >
                    {apiToken}
                </CodeSnippet>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Write-only key for use in{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/libraries" target="_blank" />}
                    >
                        client libraries
                    </Button>
                    . Safe to use in public apps.
                </Text>
            </TeamVariableCard>

            <div className="flex flex-wrap gap-4">
                <TeamVariableCard title="Project ID" className="min-w-60 flex-1">
                    <CodeSnippet compact thing="project ID">
                        {projectId}
                    </CodeSnippet>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Use this ID in the{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to="https://posthog.com/docs/api" target="_blank" />}
                        >
                            PostHog API
                        </Button>
                        .
                    </Text>
                </TeamVariableCard>
                {region ? (
                    <TeamVariableCard title="Region" className="min-w-60 flex-1">
                        <CodeSnippet compact thing="project region">
                            {`${region} Cloud`}
                        </CodeSnippet>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Where your PostHog data is hosted.
                        </Text>
                    </TeamVariableCard>
                ) : null}
            </div>
        </div>
    )
}
