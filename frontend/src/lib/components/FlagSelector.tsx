import { useValues } from 'kea'
import { useState } from 'react'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { FeatureFlagBasicType } from '~/types'

interface FlagSelectorProps {
    value: number | undefined
    onChange: (id: number, key: string, flag: FeatureFlagBasicType) => void
    readOnly?: boolean
    disabledReason?: string
    initialButtonLabel?: string
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
    // stored can't linger. It ranks below `flagKey` because a pick from the recents list carries no
    // key and falls back to `name`, which on a flag holds the description rather than a title.
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
    // Recently-used flags are persisted with just `{ name, id }` (no `key`), so a pick from the
    // recents list has nothing to label the button with until the live lookup resolves. Hold
    // whatever the picker handed us to cover that gap.
    const [selectedFlag, setSelectedFlag] = useState<PickedFlag | undefined>(undefined)

    const { featureFlag } = useValues(featureFlagLogic({ id: value || 'link' }))

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.FeatureFlags,
        value: value,
        onChange: (_, __, item) => {
            // The picker can hand back an item with no flag id; that isn't a selection.
            if ('id' in item && item.id) {
                setSelectedFlag({ id: item.id, label: item.key || item.name })
                onChange(item.id, item.key, item)
                setVisible(false)
            }
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
