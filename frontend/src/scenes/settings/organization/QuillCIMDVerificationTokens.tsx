import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Field,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Input,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconKey } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { CIMDVerificationToken, cimdVerificationTokensLogic, validateCimdUrl } from './cimdVerificationTokensLogic'

const CIMD_URL_PLACEHOLDER = 'https://example.com/.well-known/oauth-client-metadata.json'
const CIMD_URL_HELP =
    'The token only verifies at this URL, so a copy published anywhere else is ignored. Must be HTTPS and include a path, and the path is case-sensitive.'

export function QuillCIMDVerificationTokens({
    hasUnboundToken,
    tokenIssuerUrl,
    tokenIssuerHost,
    onRevoke,
}: {
    hasUnboundToken: boolean
    /** The instance that issues every token, when it is not this one. */
    tokenIssuerUrl: string | null | undefined
    tokenIssuerHost: string | null
    onRevoke: (token: CIMDVerificationToken) => void
}): JSX.Element {
    const {
        tokens,
        tokensLoading,
        isCreateDialogOpen,
        isCreatingToken,
        newTokenLabel,
        newTokenUrl,
        justCreatedToken,
        bindingToken,
        bindUrl,
        isBindingToken,
    } = useValues(cimdVerificationTokensLogic)
    const {
        showCreateDialog,
        hideCreateDialog,
        setNewTokenLabel,
        setNewTokenUrl,
        createToken,
        setJustCreatedToken,
        showBindDialog,
        hideBindDialog,
        setBindUrl,
        bindToken,
    } = useActions(cimdVerificationTokensLogic)

    const columns: ColumnDef<CIMDVerificationToken>[] = [
        {
            id: 'label',
            header: 'Label',
            cell: ({ row }) => (
                <Text size="xs" weight="semibold" render={<span />}>
                    {row.original.label}
                </Text>
            ),
        },
        {
            id: 'cimd_url',
            header: 'Metadata URL',
            cell: ({ row }) =>
                row.original.cimd_url ? (
                    <span className="font-mono text-xs break-all">{row.original.cimd_url}</span>
                ) : (
                    <Badge variant="warning">Not verifying</Badge>
                ),
        },
        {
            id: 'mask_value',
            header: 'Token',
            cell: ({ row }) => (
                <code data-quill className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs">
                    {row.original.mask_value ?? '-'}
                </code>
            ),
        },
        {
            id: 'created_at',
            header: 'Created',
            cell: ({ row }) => (
                <Text size="xs" variant="muted" render={<span />}>
                    {humanFriendlyDetailedTime(row.original.created_at)}
                </Text>
            ),
        },
        {
            id: 'last_used_at',
            header: 'Last used',
            cell: ({ row }) => (
                <Text size="xs" variant="muted" render={<span />}>
                    {row.original.last_used_at ? humanFriendlyDetailedTime(row.original.last_used_at) : 'Never'}
                </Text>
            ),
        },
        {
            id: 'actions',
            header: '',
            meta: { align: 'right' },
            cell: ({ row }) => (
                <div className="flex justify-end gap-1">
                    {!row.original.cimd_url && (
                        <Button
                            size="icon"
                            aria-label="Set metadata URL"
                            tooltip="Set metadata URL"
                            onClick={() => showBindDialog(row.original)}
                        >
                            <IconPencil />
                        </Button>
                    )}
                    <Button
                        size="icon"
                        variant="destructive-outline"
                        aria-label="Revoke token"
                        tooltip="Revoke token"
                        onClick={() => onRevoke(row.original)}
                    >
                        <IconTrash />
                    </Button>
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" render={<p className="m-0" />}>
                Verification tokens link a CIMD partner application to this organization. Add the token to your CIMD
                metadata document as <code>verification_token</code> inside the <code>com.posthog</code> object.
                Verified partners get a higher default rate limit for account provisioning and a clear identity trail.
                Each token verifies only at the metadata URL you name when creating it. See the{' '}
                <Button
                    variant="link"
                    size="inline"
                    nativeButton={false}
                    render={
                        <LinkPrimitive
                            to="https://posthog.com/docs/integrate/provisioning#host-a-cimd-metadata-document"
                            target="_blank"
                        />
                    }
                >
                    docs
                </Button>{' '}
                for the metadata format.
            </Text>

            {tokenIssuerHost && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Verification tokens are created in another PostHog region. Create the token from your
                            organization at{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={
                                    <LinkPrimitive
                                        to={`${tokenIssuerUrl}/settings/organization-cimd-verification-tokens`}
                                        target="_blank"
                                    />
                                }
                            >
                                {tokenIssuerHost}
                            </Button>
                            . Your metadata document carries one token for every region.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            <div className="flex justify-end">
                <Button
                    variant="primary"
                    onClick={showCreateDialog}
                    data-attr="create-cimd-verification-token"
                    disabledReason={tokenIssuerUrl ? `Create verification tokens at ${tokenIssuerHost}` : undefined}
                >
                    Create verification token
                </Button>
            </div>

            {hasUnboundToken && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Some tokens were issued before URL binding and have stopped verifying. Set a metadata URL on
                            each one below to restore verification.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {tokensLoading && tokens.length === 0 ? (
                <Skeleton className="h-24 w-full" />
            ) : tokens.length === 0 ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconKey />
                        </EmptyMedia>
                        <EmptyTitle>No verification tokens</EmptyTitle>
                        <EmptyDescription>
                            {tokenIssuerUrl
                                ? `Create a token at ${tokenIssuerHost} to link a CIMD partner app.`
                                : 'Create one to link a CIMD partner app to this organization.'}
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <DataTable columns={columns} data={tokens} getRowId={(token) => String(token.id)} fullWidth />
            )}

            <Dialog open={isCreateDialogOpen} onOpenChange={(open) => !open && hideCreateDialog()}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Create CIMD verification token</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <FieldGroup>
                            <Field>
                                <FieldLabel htmlFor="cimd-token-label">Label</FieldLabel>
                                <Input
                                    id="cimd-token-label"
                                    placeholder="e.g. Production CIMD partner"
                                    value={newTokenLabel}
                                    onChange={(event) => setNewTokenLabel(event.target.value)}
                                    autoFocus
                                />
                                <FieldDescription>
                                    Pick a label that helps you identify this token later. You'll only see the plaintext
                                    value once.
                                </FieldDescription>
                            </Field>
                            <Field>
                                <FieldLabel htmlFor="cimd-token-url">CIMD metadata URL</FieldLabel>
                                <Input
                                    id="cimd-token-url"
                                    placeholder={CIMD_URL_PLACEHOLDER}
                                    value={newTokenUrl}
                                    onChange={(event) => setNewTokenUrl(event.target.value)}
                                />
                                <FieldDescription>{CIMD_URL_HELP}</FieldDescription>
                            </Field>
                        </FieldGroup>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={hideCreateDialog}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={() => createToken()}
                            loading={isCreatingToken}
                            disabledReason={
                                !newTokenLabel.trim()
                                    ? 'Please enter a label'
                                    : (validateCimdUrl(newTokenUrl.trim()) ?? undefined)
                            }
                            data-attr="confirm-create-cimd-verification-token"
                        >
                            Create token
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog
                open={!!justCreatedToken}
                onOpenChange={(open) => !open && setJustCreatedToken(null)}
                disablePointerDismissal
            >
                <DialogContent showCloseButton={false}>
                    <DialogHeader>
                        <DialogTitle>Token created</DialogTitle>
                    </DialogHeader>
                    {justCreatedToken && (
                        <DialogBody>
                            <div className="flex flex-col gap-3">
                                <Item tone="warning" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            Copy this token now - you won't be able to see it again. If you lose it,
                                            you'll need to revoke and create a new one.
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                                <Text size="xs" render={<p className="m-0" />}>
                                    Add it to your CIMD metadata document as <code>verification_token</code> inside the{' '}
                                    <code>com.posthog</code> object.
                                </Text>
                                <CodeSnippet language={Language.Text}>{justCreatedToken.value}</CodeSnippet>
                            </div>
                        </DialogBody>
                    )}
                    <DialogFooter>
                        <Button variant="primary" onClick={() => setJustCreatedToken(null)}>
                            Done
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={!!bindingToken} onOpenChange={(open) => !open && hideBindDialog()}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Set metadata URL</DialogTitle>
                    </DialogHeader>
                    {bindingToken && (
                        <DialogBody>
                            <div className="flex flex-col gap-2">
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    {`"${bindingToken.label}" was issued before URL binding and has stopped verifying. Set the metadata URL it should verify at to restore verification.`}
                                </Text>
                                <Field>
                                    <FieldLabel htmlFor="cimd-token-bind-url">CIMD metadata URL</FieldLabel>
                                    <Input
                                        id="cimd-token-bind-url"
                                        placeholder={CIMD_URL_PLACEHOLDER}
                                        value={bindUrl}
                                        onChange={(event) => setBindUrl(event.target.value)}
                                        autoFocus
                                    />
                                    <FieldDescription>{CIMD_URL_HELP}</FieldDescription>
                                </Field>
                            </div>
                        </DialogBody>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={hideBindDialog}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={() => bindToken()}
                            loading={isBindingToken}
                            disabledReason={validateCimdUrl(bindUrl.trim()) ?? undefined}
                            data-attr="confirm-bind-cimd-verification-token"
                        >
                            Set URL
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
