import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { Experiment } from '~/types'

export const VariantsPanelHeader = ({ experiment }: { experiment: Experiment }): JSX.Element => {
    const flagKey = experiment.feature_flag_key
    const variants = experiment.parameters?.feature_flag_variants || []

    // Validation logic
    const hasFlagKey = !!flagKey
    const hasEnoughVariants = variants.length >= 2
    const totalRollout = variants.reduce((sum, v) => sum + (v.rollout_percentage || 0), 0)
    const isValidRollout = totalRollout === 100

    const isValid = hasFlagKey && hasEnoughVariants && isValidRollout
    const isWarning = hasFlagKey && hasEnoughVariants && !isValidRollout

    // Build summary
    const summaryParts: string[] = []

    if (!hasFlagKey) {
        summaryParts.push('No flag key configured')
    } else {
        summaryParts.push(flagKey)

        if (variants.length === 2) {
            // For 2 variants, show their names with percentages
            const variantDisplay = variants.map((v) => `${v.key} (${v.rollout_percentage || 0}%)`).join(' vs ')
            summaryParts.push(variantDisplay)
        } else if (variants.length > 2) {
            // For 3+ variants, show count and distribution
            const distribution = variants.map((v) => `${v.rollout_percentage || 0}%`).join('/')
            summaryParts.push(`${variants.length} variants (${distribution})`)
        } else if (variants.length === 1) {
            summaryParts.push('1 variant (need at least 2)')
        } else {
            summaryParts.push('No variants configured')
        }
    }

    const summaryText = summaryParts.join(' • ')

    return (
        <Tooltip title={`Feature flag & variants • ${summaryText}`}>
            <div className="flex items-center gap-2 w-full min-w-0">
                {isValid ? (
                    <IconCheckCircle className="text-success w-4 h-4 shrink-0" />
                ) : isWarning ? (
                    <IconWarning className="text-warning w-4 h-4 shrink-0" />
                ) : (
                    <IconErrorOutline className="text-danger w-4 h-4 shrink-0" />
                )}
                <span className="font-semibold shrink-0">Feature flag & variants</span>
                <span className="text-muted shrink-0">•</span>
                <span className="text-sm text-muted truncate">{summaryText}</span>
            </div>
        </Tooltip>
    )
}
