import { useActions, useValues } from 'kea'

import { IconInfo, IconX } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FlagSelector } from 'lib/components/FlagSelector'
import { ANY_VARIANT, variantOptions } from 'lib/components/IngestionControls/triggers/FlagTrigger/VariantSelector'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagBasicType, FeatureFlagType } from '~/types'

import { productTourLogic } from '../productTourLogic'

type FlagType = FeatureFlagBasicType | FeatureFlagType

export function LinkedFlagField({ id }: { id: string }): JSX.Element {
    const { productTourForm, entityKeyword } = useValues(productTourLogic({ id }))
    const { setProductTourFormValue } = useActions(productTourLogic({ id }))

    const conditions = productTourForm.content?.conditions || {}
    const flagId = productTourForm.linked_flag_id
    const flag = productTourForm.linked_flag
    const variant = conditions.linkedFlagVariant

    const handleFlagSelect = (
        selectedFlagId: number | undefined,
        _key: string,
        selectedFlag: FlagType | undefined
    ): void => {
        setProductTourFormValue('linked_flag_id', selectedFlagId ?? null)

        if (selectedFlagId && !selectedFlag) {
            // Flag ID provided but no flag object - fetch it
            api.featureFlags
                .get(selectedFlagId)
                .then((fetchedFlag) => {
                    setProductTourFormValue('linked_flag', fetchedFlag)
                })
                .catch(() => {
                    lemonToast.error('Failed to load feature flag')
                    setProductTourFormValue('linked_flag_id', null)
                    setProductTourFormValue('linked_flag', null)
                })
        } else {
            setProductTourFormValue('linked_flag', selectedFlag ?? null)
        }

        // Reset variant when flag changes
        const { linkedFlagVariant: _, ...restConditions } = conditions
        setProductTourFormValue('content', {
            ...productTourForm.content,
            conditions: restConditions,
        })
    }

    const handleClear = (): void => {
        setProductTourFormValue('linked_flag_id', null)
        setProductTourFormValue('linked_flag', null)

        const { linkedFlagVariant: _, ...restConditions } = conditions
        setProductTourFormValue('content', {
            ...productTourForm.content,
            conditions: restConditions,
        })
    }

    const handleVariantSelect = (selectedVariant: string): void => {
        setProductTourFormValue('content', {
            ...productTourForm.content,
            conditions: {
                ...conditions,
                linkedFlagVariant: selectedVariant === ANY_VARIANT ? null : selectedVariant,
            },
        })
    }

    return (
        <div className="mt-3">
            <div className="flex items-center gap-2" data-attr="linked-flag-field">
                <FlagSelector
                    value={flagId ?? undefined}
                    onChange={handleFlagSelect}
                    initialButtonLabel="Link feature flag"
                />
                {flagId && (
                    <LemonButton
                        icon={<IconX />}
                        size="small"
                        type="tertiary"
                        onClick={handleClear}
                        aria-label="Clear linked flag"
                    />
                )}
                <Tooltip
                    title={`Connecting to a feature flag will enable this ${entityKeyword} for everyone in the feature flag, as long as they match the rest of the conditions you define here.`}
                >
                    <IconInfo className="text-muted-alt text-base" />
                </Tooltip>
            </div>

            {flag?.filters.multivariate && (
                <div className="mt-2">
                    <div className="text-sm text-secondary mb-1">Variant</div>
                    <LemonSegmentedButton
                        size="small"
                        value={variant ?? ANY_VARIANT}
                        options={variantOptions(flag.filters.multivariate || undefined)}
                        onChange={handleVariantSelect}
                    />
                </div>
            )}
        </div>
    )
}
