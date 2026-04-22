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

    return (
        <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-muted">Variants</label>
            <LemonCollapse
                multiple
                defaultActiveKeys={[]}
                className="[&_.LemonCollapsePanel:not(:last-child)]:border-b [&_.LemonCollapsePanel:not(:last-child)]:border-border-secondary"
                panels={variants.map((variant, index) => {
                    const hasExpandableContent = !!(variant.name || payloads[index])
                    return {
                        key: `variant-${index}`,
                        className: '!pl-[2.5rem] dark:bg-surface-secondary',
                        header: (
                            <div className="flex gap-2 items-center">
                                <Lettermark
                                    name={alphabet[index] ?? String(index + 1)}
                                    color={LettermarkColor.Gray}
                                    size="small"
                                />
                                <span className="text-sm font-medium font-mono">
                                    {variant.key || `Variant ${index + 1}`}
                                </span>
                                <span className="text-xs text-muted">{variant.rollout_percentage || 0}%</span>
                            </div>
                        ),
                        content: hasExpandableContent ? (
                            <div className="flex flex-col gap-3">
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
                        ) : null,
                    }
                })}
            />
        </div>
    )
}
