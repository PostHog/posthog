import { IconRefresh } from '@posthog/icons'
import { Button, Card, CardContent, Item, ItemActions, ItemContent, ItemDescription, Skeleton } from '@posthog/quill'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'

import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'

export function QuillIdentityVerificationSecret({
    secret,
    previousSecretValidUntil,
    loading,
    showSkeleton,
    loadFailed,
    canManageSecret,
    onRetry,
    onRotate,
    onExpirePrevious,
}: {
    secret: string | null
    previousSecretValidUntil: string | null
    loading: boolean
    showSkeleton: boolean
    loadFailed: boolean
    canManageSecret: boolean
    onRetry: () => void
    onRotate: () => void
    onExpirePrevious: () => void
}): JSX.Element {
    return (
        <QuillSettingsSubsection
            title="Identity verification secret"
            description="Signs the identity hashes that verify who a user is in the support widget. Only use it server-side and keep it out of client code."
        >
            <Card size="sm" className="max-w-200">
                <CardContent className="flex flex-col gap-2">
                    {showSkeleton ? (
                        <Skeleton className="h-10" />
                    ) : loadFailed ? (
                        <Item tone="destructive" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    Couldn't load the identity verification secret. Retry, and if it keeps happening
                                    contact support.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button variant="outline" onClick={onRetry}>
                                    Retry
                                </Button>
                            </ItemActions>
                        </Item>
                    ) : (
                        <>
                            <CodeSnippet
                                actions={
                                    <Button
                                        size="icon"
                                        data-attr="conversations-rotate-signing-secret"
                                        onClick={onRotate}
                                        loading={loading}
                                        disabledReason={
                                            !canManageSecret
                                                ? 'You do not have permission to rotate this secret'
                                                : undefined
                                        }
                                        aria-label={secret ? 'Rotate secret' : 'Generate secret'}
                                        tooltip={secret ? 'Rotate secret' : 'Generate secret'}
                                    >
                                        <IconRefresh />
                                    </Button>
                                }
                                className={secret ? '' : 'text-muted-foreground'}
                                thing="Identity verification secret"
                            >
                                {secret ||
                                    'No secret yet. Generate one with the button on the right to enable identity verification.'}
                            </CodeSnippet>

                            {previousSecretValidUntil ? (
                                <Item tone="info" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            The previous secret keeps verifying until{' '}
                                            <TZLabel
                                                time={previousSecretValidUntil}
                                                formatDate="MMM D, YYYY"
                                                formatTime="h:mm A"
                                            />
                                            . Update your server-side code with the new secret before then, or expire it
                                            now if it may be compromised.
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Button
                                            variant="outline"
                                            onClick={onExpirePrevious}
                                            disabledReason={
                                                !canManageSecret
                                                    ? 'You do not have permission to expire the previous secret'
                                                    : undefined
                                            }
                                            data-attr="conversations-expire-previous-signing-secret"
                                        >
                                            Expire now
                                        </Button>
                                    </ItemActions>
                                </Item>
                            ) : (
                                <Item tone="info" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            {secret
                                                ? 'Rotating this secret starts a 48-hour grace window: the previous secret keeps verifying until the window ends, then expires. Update your server-side code within that window.'
                                                : "This project doesn't have an identity verification secret yet. Identity verification in the support widget stays off until you generate one."}
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                        </>
                    )}
                </CardContent>
            </Card>
        </QuillSettingsSubsection>
    )
}
