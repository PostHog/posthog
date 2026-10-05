import { useValues } from 'kea'
import { useState } from 'react'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { FeatureFlagBasicType } from '~/types'

interface FlagSelectorProps {
    value: number | undefined
    /**
     * `flag` is absent when the picked row is a stored summary rather than the flag itself. A caller
     * that reads the flag's configuration loads it from `id` in that case.
     */
    onChange: (id: number, key: string, flag?: FeatureFlagBasicType) => void
    readOnly?: boolean
    disabledReason?: string
    initialButtonLabel?: string
}

interface PickedFeatureFlag {
    id: number
    key: string
    flag?: FeatureFlagBasicType
}

/**
 * A row from the Feature Flags list is the flag itself. A row from the Recent category is a stored
 * summary of one: it holds the id and key its label needs, and none of the flag's configuration. A
 * caller reads `filters` and `active` off the flag, so a summary must not stand in for one.
 */
export function pickedFeatureFlag(item: unknown, pickedValue: TaxonomicFilterValue): PickedFeatureFlag | null {
    const row = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    // The Feature Flags group keys every row by flag id, so the picked value carries the id even
    // when the row itself does not.
    const id = typeof row.id === 'number' ? row.id : typeof pickedValue === 'number' ? pickedValue : null
    const key = typeof row.key === 'string' && row.key ? row.key : null
    if (id === null || key === null) {
        return null
    }
    return { id, key, flag: 'filters' in row ? (row as unknown as FeatureFlagBasicType) : undefined }
}

interface PickedFlag {
    id: number
    label: string
}

export function flagSelectorButtonLabel({
    flagKey,
    value,
    pickedFlag,
    initialButtonLabel,
}: {
    flagKey: string
    value: number | undefined
    pickedFlag: PickedFlag | undefined
    initialButtonLabel: string | undefined
}): string {
    // A pick only labels the button while it still agrees with `value`, so a pick the caller never
    // stored can't linger. It ranks below `flagKey` because the lookup holds the flag's current key.
    // `flagKey` is '' both while the lookup is in flight and when it fails, which is the gap the
    // pick covers.
    const pickedLabel = pickedFlag && pickedFlag.id === value ? pickedFlag.label : undefined
    return flagKey || pickedLabel || (initialButtonLabel ?? 'Select flag')
}

export function FlagSelector({
    value,
    onChange,
    readOnly,
    disabledReason,
    initialButtonLabel,
}: FlagSelectorProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    // The live lookup of a freshly picked flag takes a moment, so hold the label the picker handed
    // us to cover that gap.
    const [selectedFlag, setSelectedFlag] = useState<PickedFlag | undefined>(undefined)

    const { featureFlag } = useValues(featureFlagLogic({ id: value || 'link' }))

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.FeatureFlags,
        value: value,
        onChange: (_, pickedValue, item) => {
            const picked = pickedFeatureFlag(item, pickedValue)
            // A row the picker cannot resolve to a flag isn't a selection. No category renders one,
            // so this only guards against a stored row shape that predates the fields above.
            if (!picked) {
                return
            }
            setSelectedFlag({ id: picked.id, label: picked.key })
            onChange(picked.id, picked.key, picked.flag)
            setVisible(false)
        },
        taxonomicGroupTypes: [TaxonomicFilterGroupType.FeatureFlags],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
        taxonomicFilterLogicKey: 'flag-selectorz',
        selectingKeyOnly: true,
    }

    const buttonLabel = flagSelectorButtonLabel({
        flagKey: featureFlag.key,
        value,
        pickedFlag: selectedFlag,
        initialButtonLabel,
    })

    return (
        <Popover
            overlay={<TaxonomicFilter {...taxonomicFilterLogicProps} />}
            visible={visible}
            placement="right-start"
            fallbackPlacements={['left-end', 'bottom']}
            onClickOutside={() => setVisible(false)}
        >
            <LemonButton
                type="secondary"
                onClick={() => setVisible(!visible)}
                disabledReason={readOnly && (disabledReason || "I'm read-only")}
            >
                {buttonLabel}
            </LemonButton>
        </Popover>
    )
}
