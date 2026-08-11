import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconKey } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { cimdVerificationTokensLogic, validateCimdUrl, CIMDVerificationToken } from './cimdVerificationTokensLogic'

export function CIMDVerificationTokens(): JSX.Element {
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
        deleteToken,
        setJustCreatedToken,
        showBindDialog,
        hideBindDialog,
        setBindUrl,
        bindToken,
    } = useActions(cimdVerificationTokensLogic)
    const hasUnboundToken = tokens.some((token) => !token.cimd_url)

    return (
        <div className="space-y-4">
            <p className="text-secondary">
                Verification tokens link a CIMD partner application to this organization. Add the token to your CIMD
                metadata document as <code>verification_token</code> inside the <code>com.posthog</code> object.
                Verified partners get a higher default rate limit for account provisioning and a clear identity trail.
                Each token verifies only at the metadata URL you name when creating it. See the{' '}
                <Link
                    to="https://posthog.com/docs/integrate/provisioning#host-a-cimd-metadata-document"
                    target="_blank"
                >
                    docs
                </Link>{' '}
                for the metadata format.
            </p>

            <div className="flex justify-end">
                <LemonButton type="primary" onClick={showCreateDialog} data-attr="create-cimd-verification-token">
                    Create verification token
                </LemonButton>
            </div>

            {hasUnboundToken && (
                <LemonBanner type="warning">
                    Some tokens were issued before URL binding and have stopped verifying. Set a metadata URL on each
                    one below to restore verification.
                </LemonBanner>
            )}

            {!tokensLoading && tokens.length === 0 ? (
                <div className="border border-dashed rounded-lg p-8 text-center">
                    <IconKey className="text-4xl text-secondary mx-auto mb-3" />
                    <h3 className="text-base font-semibold mb-1">No verification tokens</h3>
                    <p className="text-secondary">Create one to link a CIMD partner app to this organization.</p>
                </div>
            ) : (
                <LemonTable
                    loading={tokensLoading}
                    dataSource={tokens}
                    columns={[
                        {
                            title: 'Label',
                            key: 'label',
                            render: (_, row: CIMDVerificationToken) => (
                                <span className="font-semibold">{row.label}</span>
                            ),
                        },
                        {
                            title: 'Metadata URL',
                            key: 'cimd_url',
                            render: (_, row: CIMDVerificationToken) =>
                                row.cimd_url ? (
                                    <span className="text-xs font-mono break-all">{row.cimd_url}</span>
                                ) : (
                                    <LemonTag type="warning">Not verifying</LemonTag>
                                ),
                        },
                        {
                            title: 'Token',
                            key: 'mask_value',
                            render: (_, row: CIMDVerificationToken) => (
                                <code className="text-xs bg-fill-primary rounded px-1.5 py-0.5 font-mono">
                                    {row.mask_value ?? '—'}
                                </code>
                            ),
                        },
                        {
                            title: 'Created',
                            key: 'created_at',
                            render: (_, row: CIMDVerificationToken) => (
                                <span className="text-muted text-sm">{humanFriendlyDetailedTime(row.created_at)}</span>
                            ),
                        },
                        {
                            title: 'Last used',
                            key: 'last_used_at',
                            render: (_, row: CIMDVerificationToken) => (
                                <span className="text-muted text-sm">
                                    {row.last_used_at ? humanFriendlyDetailedTime(row.last_used_at) : 'Never'}
                                </span>
                            ),
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 0,
                            render: (_, row: CIMDVerificationToken) => (
                                <div className="flex gap-1">
                                    {!row.cimd_url && (
                                        <LemonButton
                                            icon={<IconPencil />}
                                            size="small"
                                            tooltip="Set metadata URL"
                                            onClick={() => showBindDialog(row)}
                                        />
                                    )}
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        status="danger"
                                        tooltip="Revoke token"
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: `Revoke token "${row.label}"?`,
                                                description:
                                                    'Partners using this token in their CIMD metadata will no longer be recognized and will fall back to the anonymous rate limit tier.',
                                                primaryButton: {
                                                    children: 'Revoke',
                                                    status: 'danger',
                                                    onClick: () => deleteToken(row),
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }
                                    />
                                </div>
                            ),
                        },
                    ]}
                />
            )}

            <LemonModal
                isOpen={isCreateDialogOpen}
                onClose={hideCreateDialog}
                title="Create CIMD verification token"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={hideCreateDialog}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
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
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-2">
                    <label className="text-sm font-semibold" htmlFor="cimd-token-label">
                        Label
                    </label>
                    <LemonInput
                        id="cimd-token-label"
                        placeholder="e.g. Production CIMD partner"
                        value={newTokenLabel}
                        onChange={setNewTokenLabel}
                        autoFocus
                    />
                    <p className="text-secondary text-xs">
                        Pick a label that helps you identify this token later. You'll only see the plaintext value once.
                    </p>

                    <label className="text-sm font-semibold pt-2 block" htmlFor="cimd-token-url">
                        CIMD metadata URL
                    </label>
                    <LemonInput
                        id="cimd-token-url"
                        placeholder="https://example.com/.well-known/oauth-client-metadata.json"
                        value={newTokenUrl}
                        onChange={setNewTokenUrl}
                    />
                    <p className="text-secondary text-xs">
                        The token only verifies at this URL, so a copy published anywhere else is ignored. Must be HTTPS
                        and include a path, and the path is case-sensitive.
                    </p>
                </div>
            </LemonModal>

            <LemonModal
                isOpen={!!justCreatedToken}
                onClose={() => setJustCreatedToken(null)}
                closable={false}
                title="Token created"
                footer={
                    <LemonButton type="primary" onClick={() => setJustCreatedToken(null)}>
                        Done
                    </LemonButton>
                }
            >
                {justCreatedToken && (
                    <div className="space-y-3">
                        <LemonBanner type="warning">
                            Copy this token now - you won't be able to see it again. If you lose it, you'll need to
                            revoke and create a new one.
                        </LemonBanner>
                        <p className="text-secondary">
                            Add it to your CIMD metadata document as <code>verification_token</code> inside the{' '}
                            <code>com.posthog</code> object.
                        </p>
                        <CodeSnippet language={Language.Text}>{justCreatedToken.value}</CodeSnippet>
                    </div>
                )}
            </LemonModal>

            <LemonModal
                isOpen={!!bindingToken}
                onClose={hideBindDialog}
                title="Set metadata URL"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={hideBindDialog}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => bindToken()}
                            loading={isBindingToken}
                            disabledReason={validateCimdUrl(bindUrl.trim()) ?? undefined}
                            data-attr="confirm-bind-cimd-verification-token"
                        >
                            Set URL
                        </LemonButton>
                    </>
                }
            >
                {bindingToken && (
                    <div className="space-y-2">
                        <p className="text-secondary text-sm">
                            "{bindingToken.label}" was issued before URL binding and has stopped verifying. Set the
                            metadata URL it should verify at to restore verification.
                        </p>
                        <label className="text-sm font-semibold" htmlFor="cimd-token-bind-url">
                            CIMD metadata URL
                        </label>
                        <LemonInput
                            id="cimd-token-bind-url"
                            placeholder="https://example.com/.well-known/oauth-client-metadata.json"
                            value={bindUrl}
                            onChange={setBindUrl}
                            autoFocus
                        />
                        <p className="text-secondary text-xs">
                            The token only verifies at this URL, so a copy published anywhere else is ignored. Must be
                            HTTPS and include a path, and the path is case-sensitive.
                        </p>
                    </div>
                )}
            </LemonModal>
        </div>
    )
}
