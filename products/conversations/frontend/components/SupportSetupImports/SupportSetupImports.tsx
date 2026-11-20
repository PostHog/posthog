import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { type SupportSetupImport, supportSetupCardLogic } from '../SupportSetupCard/supportSetupCardLogic'

interface SupportSetupImportsProps {
    mode: ProductEmptyStateMode
    preview: boolean
    /** Set when the person cannot turn Support on. Picking an import turns it on first. */
    restrictionReason: string | null
}

export function SupportSetupImports({ mode, preview, restrictionReason }: SupportSetupImportsProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { pendingImport, pendingReason } = useValues(supportSetupCardLogic)
    const { pickImport } = useActions(supportSetupCardLogic)

    const sources: { key: SupportSetupImport; label: string }[] = [
        { key: 'zendesk', label: 'Zendesk' },
        ...(featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_INTERCOM_IMPORT]
            ? [{ key: 'intercom' as const, label: 'Intercom' }]
            : []),
        ...(featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_PYLON_IMPORT]
            ? [{ key: 'pylon' as const, label: 'Pylon' }]
            : []),
    ]

    return (
        <div className="flex flex-col gap-2 border-t border-primary px-4 py-3">
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">Moving from another tool?</span>
                <span className="text-xs text-secondary">
                    Import your existing tickets, so your inbox starts with your history.
                </span>
            </div>
            <div className="flex flex-wrap gap-2">
                {sources.map((source) => (
                    <LemonButton
                        key={source.key}
                        type="secondary"
                        size="small"
                        loading={pendingImport === source.key}
                        disabledReason={
                            restrictionReason ??
                            (pendingImport !== source.key ? (pendingReason ?? undefined) : undefined)
                        }
                        onClick={() => pickImport(source.key, mode, preview)}
                        data-attr={`support-setup-import-${source.key}`}
                    >
                        Import from {source.label}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
