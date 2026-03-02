import { useActions } from 'kea'

import { IconBalance, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonTextArea,
    Lettermark,
    LettermarkColor,
} from '@posthog/lemon-ui'

import { alphabet } from 'lib/utils'

import { FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'
import { JSONEditorInput } from './JSONEditorInput'

interface FeatureFlagVariantsSectionProps {
    featureFlag: FeatureFlagType
    variants: MultivariateFlagVariant[]
    isEditing: boolean
    sectionDraft: Partial<FeatureFlagType> | null
}

export function FeatureFlagVariantsSection({
    featureFlag,
    variants: originalVariants,
    isEditing,
    sectionDraft,
}: FeatureFlagVariantsSectionProps): JSX.Element {
    const {
        updateDraftVariant,
        updateDraftVariantPayload,
        addDraftVariant,
        removeDraftVariant,
        distributeDraftVariantsEqually,
    } = useActions(featureFlagLogic)

    const draftVariants: MultivariateFlagVariant[] = sectionDraft?.filters?.multivariate?.variants ?? originalVariants
    const draftPayloads = sectionDraft?.filters?.payloads ?? featureFlag.filters?.payloads ?? {}

    const displayVariants = isEditing ? draftVariants : originalVariants
    const displayPayloads = isEditing ? draftPayloads : (featureFlag.filters?.payloads ?? {})
    const allVariantKeys = displayVariants.map((_, index) => `variant-${index}`)

    if (isEditing) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <LemonLabel>Variants</LemonLabel>
                    <LemonButton
                        size="small"
                        icon={<IconBalance />}
                        onClick={distributeDraftVariantsEqually}
                        tooltip="Distribute rollout percentages equally"
                    />
                </div>

                <LemonCollapse
                    multiple
                    defaultActiveKeys={allVariantKeys}
                    panels={displayVariants.map((variant, index) => ({
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
                            <div className="flex flex-col gap-2">
                                <LemonLabel>Variant key</LemonLabel>
                                <LemonInput
                                    placeholder="Enter a variant key - e.g. control, test, variant_1"
                                    value={variant.key}
                                    onChange={(value) => updateDraftVariant(index, 'key', value)}
                                />

                                <LemonLabel>Rollout percentage</LemonLabel>
                                <LemonInput
                                    type="number"
                                    min={0}
                                    max={100}
                                    value={variant.rollout_percentage || 0}
                                    onChange={(value) =>
                                        updateDraftVariant(
                                            index,
                                            'rollout_percentage',
                                            parseInt(value?.toString() || '0')
                                        )
                                    }
                                    suffix={<span>%</span>}
                                />

                                <LemonLabel>Description</LemonLabel>
                                <LemonTextArea
                                    placeholder="Enter an optional description for the variant"
                                    value={variant.name || ''}
                                    onChange={(value) => updateDraftVariant(index, 'name', value)}
                                />

                                <LemonLabel>Payload</LemonLabel>
                                <JSONEditorInput
                                    onChange={(value) => updateDraftVariantPayload(index, value)}
                                    value={displayPayloads[variant.key]}
                                    placeholder='{"key": "value"}'
                                />

                                {displayVariants.length > 1 && <LemonDivider />}
                                {displayVariants.length > 1 && (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        icon={<IconTrash />}
                                        onClick={() => {
                                            const variantKey = variant.key || `Variant ${index + 1}`
                                            const hasPayload = !!displayPayloads[variant.key]
                                            LemonDialog.open({
                                                title: `Remove variant "${variantKey}"?`,
                                                description: hasPayload
                                                    ? 'This variant has a payload configured. Both the variant and its payload will be deleted.'
                                                    : 'This action cannot be undone.',
                                                primaryButton: {
                                                    children: 'Remove variant',
                                                    status: 'danger',
                                                    onClick: () => removeDraftVariant(index),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        }}
                                    >
                                        Remove variant
                                    </LemonButton>
                                )}
                            </div>
                        ),
                    }))}
                />

                <div>
                    <LemonButton type="secondary" icon={<IconPlus />} onClick={addDraftVariant}>
                        Add variant
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-muted">Variants</label>
            <LemonCollapse
                multiple
                defaultActiveKeys={allVariantKeys}
                panels={displayVariants.map((variant, index) => ({
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

                            {displayPayloads[variant.key] && (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Payload</label>
                                    <JSONEditorInput readOnly value={displayPayloads[variant.key]} />
                                </div>
                            )}
                        </div>
                    ),
                }))}
            />
        </div>
    )
}
