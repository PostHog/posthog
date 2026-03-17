import { LemonCollapse, Lettermark, LettermarkColor } from '@posthog/lemon-ui'

import { alphabet } from 'lib/utils'

import { FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { JSONEditorInput } from './JSONEditorInput'

interface FeatureFlagVariantsSectionProps {
    featureFlag: FeatureFlagType
    variants: MultivariateFlagVariant[]
}

export function FeatureFlagVariantsSection({ featureFlag, variants }: FeatureFlagVariantsSectionProps): JSX.Element {
    const payloads = featureFlag.filters?.payloads ?? {}
    const allVariantKeys = variants.map((_, index) => `variant-${index}`)

    return (
        <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-muted">Variants</label>
            <LemonCollapse
                multiple
                defaultActiveKeys={allVariantKeys}
                panels={variants.map((variant, index) => ({
                    key: `variant-${index}`,
                    header: (
                        <div className="flex gap-2 items-center">
                            <Lettermark
                                name={alphabet[index] ?? String(index + 1)}
                                color={LettermarkColor.Gray}
                                size="small"
                            />
                            <span className="text-sm font-medium">{variant.key || `Variant ${index + 1}`}</span>
                            <span className="text-xs text-muted">({variant.rollout_percentage || 0}%)</span>
                        </div>
                    ),
                    content: (
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-col gap-1">
                                <label className="text-xs font-medium text-muted">Variant key</label>
                                <div className="font-mono text-sm">{variant.key}</div>
                            </div>

                            <div className="flex flex-col gap-1">
                                <label className="text-xs font-medium text-muted">Rollout percentage</label>
                                <div className="text-sm font-semibold">{variant.rollout_percentage || 0}%</div>
                            </div>

                            {variant.name && (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Description</label>
                                    <div className="text-sm">{variant.name}</div>
                                </div>
                            )}

                            {payloads[index] && (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Payload</label>
                                    <JSONEditorInput readOnly value={payloads[index]} />
                                </div>
                            )}
                        </div>
                    ),
                }))}
            />
        </div>
    )
}
