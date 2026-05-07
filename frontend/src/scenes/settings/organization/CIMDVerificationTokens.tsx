import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconKey } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { cimdVerificationTokensLogic, CIMDVerificationToken } from './cimdVerificationTokensLogic'

export function CIMDVerificationTokens(): JSX.Element {
    const { tokens, tokensLoading, isCreateDialogOpen, newTokenLabel, justCreatedToken } =
        useValues(cimdVerificationTokensLogic)
    const { showCreateDialog, hideCreateDialog, setNewTokenLabel, createToken, deleteToken, setJustCreatedToken } =
        useActions(cimdVerificationTokensLogic)

    return (
        <div className="space-y-4">
            <p className="text-secondary">
                Verification tokens link a CIMD partner application to this organization. Add the token to your CIMD
                metadata document under <code>posthog_verification_token</code>. Verified partners get a higher default
                rate limit for account provisioning and a clear identity trail. See the{' '}
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
                            disabledReason={!newTokenLabel.trim() ? 'Please enter a label' : undefined}
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
                            Add it to your CIMD metadata document as the <code>posthog_verification_token</code> field.
                        </p>
                        <CodeSnippet language={Language.Text}>{justCreatedToken.value}</CodeSnippet>
                    </div>
                )}
            </LemonModal>
        </div>
    )
}
