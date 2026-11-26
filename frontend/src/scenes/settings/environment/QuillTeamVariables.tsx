import { IconRefresh } from '@posthog/icons'
import { Button, InputGroupButton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillCopyField } from 'scenes/settings/components/QuillCopyField'

import { Region } from '~/types'

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
        <div className="grid max-w-200 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
                <QuillCopyField
                    label="Project token"
                    description="project token"
                    value={apiToken}
                    data-attr="copy-code-button"
                    helpText={
                        <>
                            Write-only key for{' '}
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
                    actions={
                        isTokenResetAvailable ? (
                            <InputGroupButton
                                size="icon-xs"
                                aria-label="Reset token"
                                tooltip="Reset token"
                                disabledReason={restrictedReason}
                                onClick={onResetToken}
                            >
                                <IconRefresh />
                            </InputGroupButton>
                        ) : undefined
                    }
                />
            </div>
            <QuillCopyField
                label="Project ID"
                description="project ID"
                value={projectId}
                data-attr="copy-code-button"
                helpText={
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
                <QuillCopyField
                    label="Region"
                    description="project region"
                    value={`${region} Cloud`}
                    data-attr="copy-code-button"
                    helpText="Where your PostHog data is hosted."
                />
            ) : null}
        </div>
    )
}
