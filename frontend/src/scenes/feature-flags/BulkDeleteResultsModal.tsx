import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCopy, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonModal } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DeletedFlagInfo, FlagRolloutState, flagSelectionLogic } from './flagSelectionLogic'

function generateCleanupPrompt(deletedFlags: DeletedFlagInfo[]): string {
    if (deletedFlags.length === 0) {
        return ''
    }

    const fullyRolledOut = deletedFlags.filter((f) => f.rollout_state === 'fully_rolled_out')
    const notRolledOut = deletedFlags.filter((f) => f.rollout_state === 'not_rolled_out')
    const partial = deletedFlags.filter((f) => f.rollout_state === 'partial')

    const sections: string[] = []

    sections.push('Find and remove all references to these deleted feature flags in the codebase.')
    sections.push(
        'For each flag, search for all usages: isFeatureEnabled, useFeatureFlag, getFeatureFlag, posthog.isFeatureEnabled, posthog.getFeatureFlag, etc.'
    )

    if (fullyRolledOut.length > 0) {
        const booleanFlags = fullyRolledOut.filter((f) => !f.active_variant)
        const variantFlags = fullyRolledOut.filter((f) => f.active_variant)

        sections.push('\n## Flags that were rolled out to 100%')
        sections.push('These flags were fully rolled out. Remove the flag check but KEEP the enabled code path.')

        if (booleanFlags.length > 0) {
            const flagList = booleanFlags.map((f) => `- ${f.key}`).join('\n')
            sections.push(`\nBoolean flags (remove the if-check, keep the body):\n${flagList}`)
            sections.push(`Example:
\`\`\`diff
- if (isFeatureEnabled('${booleanFlags[0].key}')) {
      doStuff();
- }
\`\`\`

If there is an else branch, remove it entirely:
\`\`\`diff
- if (isFeatureEnabled('${booleanFlags[0].key}')) {
      doStuff();
- } else {
-     doOtherStuff();
- }
\`\`\``)
        }

        if (variantFlags.length > 0) {
            const flagList = variantFlags.map((f) => `- ${f.key} (keep variant: "${f.active_variant}")`).join('\n')
            sections.push(`\nMultivariate flags (keep the winning variant's code, remove the flag check):\n${flagList}`)
            sections.push(`Example:
\`\`\`diff
- if (getFeatureFlag('${variantFlags[0].key}') === '${variantFlags[0].active_variant}') {
      doStuff();
- }
\`\`\`

For switch statements, keep only the winning variant's code:
\`\`\`diff
- switch (getFeatureFlag('${variantFlags[0].key}')) {
-     case '${variantFlags[0].active_variant}':
          doStuff();
-         break;
-     case 'other-variant':
-         doOtherStuff();
-         break;
- }
\`\`\``)
        }
    }

    if (notRolledOut.length > 0) {
        const flagList = notRolledOut.map((f) => `- ${f.key}`).join('\n')
        sections.push('\n## Flags that were rolled out to 0% or never called')
        sections.push('These flags were never active. Remove the entire flag check AND the enabled code path.')
        sections.push(flagList)
        sections.push(`Example:
\`\`\`diff
- if (isFeatureEnabled('${notRolledOut[0].key}')) {
-     doStuff();
- }
\`\`\`

If there is an else branch, keep only the else body:
\`\`\`diff
- if (isFeatureEnabled('${notRolledOut[0].key}')) {
-     doStuff();
- } else {
      doOtherStuff();
- }
\`\`\``)
    }

    if (partial.length > 0) {
        const flagList = partial.map((f) => `- ${f.key}`).join('\n')
        sections.push('\n## Flags with partial rollout')
        sections.push(
            "These flags had a partial rollout. Check the flag's intent to determine which code path to keep, then remove the flag check."
        )
        sections.push(flagList)
    }

    sections.push('\nAfter cleanup, remove any dead code branches and unused imports.')

    return sections.join('\n')
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
        setTimeout(() => setCopied(false), 2000)
    }

    return (
        <LemonModal
            isOpen={resultsModalVisible}
            onClose={hideResultsModal}
            title="Bulk deletion results"
            width={600}
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
                        <FlagResultsList flags={deleted} />
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
                                        <span>Clean up code references with AI</span>
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

function FlagResultsList({ flags }: { flags: DeletedFlagInfo[] }): JSX.Element {
    const stateLabels: Record<FlagRolloutState, string> = {
        fully_rolled_out: 'was 100% rolled out',
        not_rolled_out: 'was at 0% / never called',
        partial: 'had partial rollout',
    }

    return (
        <ul className="list-none pl-6 space-y-1">
            {flags.map((flag) => (
                <li key={flag.id} className="text-sm text-muted">
                    <span>{flag.key}</span>
                    <span className="text-muted-alt">
                        {' '}
                        — {stateLabels[flag.rollout_state] ?? 'unknown state'}
                        {flag.active_variant ? ` (variant: "${flag.active_variant}")` : ''}
                    </span>
                </li>
            ))}
        </ul>
    )
}
