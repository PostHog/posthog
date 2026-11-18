import { IconCopy, IconRefresh } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { Region } from '~/types'

function TeamVariableRow({
    title,
    description,
    value,
    thing,
    extraAction,
}: {
    title: string
    description: React.ReactNode
    value: string
    thing: string
    extraAction?: React.ReactNode
}): JSX.Element {
    return (
        <Item variant="outline" className="flex-wrap">
            <ItemContent className="min-w-60">
                <ItemTitle>{title}</ItemTitle>
                <ItemDescription>{description}</ItemDescription>
            </ItemContent>
            <ItemActions className="min-w-0">
                <code data-quill className="truncate rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs select-all">
                    {value}
                </code>
                <Button
                    size="icon-sm"
                    aria-label={`Copy ${thing}`}
                    tooltip={`Copy ${thing}`}
                    onClick={() => void copyToClipboard(value, thing)}
                    data-attr="copy-code-button"
                >
                    <IconCopy />
                </Button>
                {extraAction}
            </ItemActions>
        </Item>
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
        <ItemGroup combined className="max-w-200">
            <TeamVariableRow
                title="Project token"
                thing="project token"
                value={apiToken}
                description={
                    <>
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
                    </>
                }
                extraAction={
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
            />
            <TeamVariableRow
                title="Project ID"
                thing="project ID"
                value={projectId}
                description={
                    <>
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
                    </>
                }
            />
            {region ? (
                <TeamVariableRow
                    title="Region"
                    thing="project region"
                    value={`${region} Cloud`}
                    description="Where your PostHog data is hosted."
                />
            ) : null}
        </ItemGroup>
    )
}
