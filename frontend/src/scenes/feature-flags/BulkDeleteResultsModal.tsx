import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCopy, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonModal, lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { BulkDeleteResult, flagSelectionLogic } from './flagSelectionLogic'

function generateCleanupPrompt(deletedFlags: BulkDeleteResult['deleted']): string {
    if (deletedFlags.length === 0) {
        return ''
    }

    const flagList = deletedFlags.map((f) => `- ${f.key}`).join('\n')

    return `Find and remove all references to these feature flags in the codebase:
${flagList}

For each flag:
1. Find all usages (isFeatureEnabled, useFeatureFlag, posthog.isFeatureEnabled, etc.)
2. Replace with the default value (true for 100% rollout flags)
3. Remove the flag check entirely if possible
4. Clean up any dead code branches`
}

export function BulkDeleteResultsModal(): JSX.Element | null {
    const { bulkDeleteResult, resultsModalVisible } = useValues(flagSelectionLogic)
    const { hideResultsModal } = useActions(flagSelectionLogic)
    const [copied, setCopied] = useState(false)

    if (!bulkDeleteResult || !resultsModalVisible) {
        return null
    }

    const { deleted, errors } = bulkDeleteResult
    const cleanupPrompt = generateCleanupPrompt(deleted)

    const handleCopyPrompt = async (): Promise<void> => {
        await copyToClipboard(cleanupPrompt, 'cleanup prompt')
        setCopied(true)
        lemonToast.success('Copied cleanup prompt to clipboard')
        setTimeout(() => setCopied(false), 2000)
    }

    return (
        <LemonModal
            isOpen={resultsModalVisible}
            onClose={hideResultsModal}
            title="Bulk delete results"
            footer={
                <LemonButton type="primary" onClick={hideResultsModal}>
                    Done
                </LemonButton>
            }
        >
            <div className="space-y-4">
                {deleted.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-success font-medium">
                            <IconCheck className="text-lg" />
                            <span>
                                Deleted {deleted.length} flag{deleted.length !== 1 ? 's' : ''}
                            </span>
                        </div>
                        <ul className="list-none pl-6 space-y-1">
                            {deleted.map((flag: { id: number; key: string }) => (
                                <li key={flag.id} className="text-sm text-muted">
                                    {flag.key}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {errors.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-danger font-medium">
                            <IconX className="text-lg" />
                            <span>
                                Failed to delete {errors.length} flag{errors.length !== 1 ? 's' : ''}
                            </span>
                        </div>
                        <ul className="list-none pl-6 space-y-1">
                            {errors.map((error: { id: number; key?: string; reason: string }, i: number) => (
                                <li key={error.id || i} className="text-sm">
                                    <span className="text-muted">{error.key || `ID: ${error.id}`}</span>
                                    <span className="text-muted-alt"> — {error.reason}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {deleted.length > 0 && (
                    <LemonCollapse
                        panels={[
                            {
                                key: 'cleanup',
                                header: (
                                    <div className="flex items-center gap-2">
                                        <IconWarning className="text-warning" />
                                        <span>Clean up code references</span>
                                    </div>
                                ),
                                content: (
                                    <div className="space-y-3">
                                        <p className="text-sm text-muted">
                                            Copy this prompt to your AI code editor (Claude Code, Cursor, Copilot, etc.)
                                            to help remove flag references from your codebase:
                                        </p>
                                        <pre className="text-xs bg-bg-3000 p-3 rounded overflow-x-auto whitespace-pre-wrap">
                                            {cleanupPrompt}
                                        </pre>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            icon={copied ? <IconCheck /> : <IconCopy />}
                                            onClick={handleCopyPrompt}
                                        >
                                            {copied ? 'Copied!' : 'Copy prompt'}
                                        </LemonButton>
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
            </div>
        </LemonModal>
    )
}
