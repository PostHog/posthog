import clsx from 'clsx'
import { useValues } from 'kea'
import { Fragment } from 'react'
import { match } from 'ts-pattern'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { Experiment } from '~/types'

import { variantsPanelLogic } from './variantsPanelLogic'
import { buildVariantSummary, validateVariants } from './variantsPanelValidation'

const FlagKeyText = ({ flagKey }: { flagKey: string }): JSX.Element => (
    <LemonTag type="muted" className="font-mono">
        {flagKey}
    </LemonTag>
)

export const VariantsPanelHeader = ({ experiment }: { experiment: Experiment }): JSX.Element => {
    const { featureFlagKeyValidation } = useValues(variantsPanelLogic({ experiment }))

    const flagKey = experiment.feature_flag_key
    const variants = experiment.parameters?.feature_flag_variants || []

    const result = validateVariants({ flagKey, variants, featureFlagKeyValidation })

    const { hasErrors, hasWarnings, rules } = result
    const { hasFlagKey, hasFlagKeyError } = rules

    const summaryParts: (string | JSX.Element)[] = match({ hasFlagKey, hasFlagKeyError })
        .with({ hasFlagKey: false }, () => ['No flag key configured'])
        .with({ hasFlagKey: true, hasFlagKeyError: true }, () => [
            <FlagKeyText flagKey={flagKey} />,
            featureFlagKeyValidation?.error || 'Invalid flag key',
        ])
        .with({ hasFlagKey: true, hasFlagKeyError: false }, () => {
            /**
             * if the flag key is valid, we can show the variant summary
             */
            const variantSummary = match(variants.length)
                .with(0, () => 'No variants configured') //this should never happen
                .with(1, () => '1 variant (need at least 2)') //this should never happen
                .otherwise(() => buildVariantSummary(variants, result))

            return [<FlagKeyText flagKey={flagKey} />, variantSummary]
        })
        .exhaustive()

    return (
        <div className="flex items-center gap-2 w-full min-w-0">
            {hasErrors ? (
                <IconErrorOutline className="text-danger w-4 h-4 shrink-0" />
            ) : hasWarnings ? (
                <IconWarning className="text-warning w-4 h-4 shrink-0" />
            ) : (
                <IconCheckCircle className="text-success w-4 h-4 shrink-0" />
            )}
            <span className="font-semibold shrink-0">Feature flag & variants</span>
            <span className="text-muted shrink-0">•</span>
            <span
                className={clsx(
                    'text-sm truncate',
                    hasErrors ? 'text-danger' : hasWarnings ? 'text-warning' : 'text-muted'
                )}
            >
                {summaryParts.map((part, i) => (
                    <Fragment key={i}>
                        {i > 0 && <span className="text-muted shrink-0"> • </span>}
                        {typeof part === 'string' ? part : part}
                    </Fragment>
                ))}
            </span>
        </div>
    )
}
