import { useValues } from 'kea'
import { useEffect, useState } from 'react'

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

export function FlagSelector({
    value,
    onChange,
    readOnly,
    disabledReason,
    initialButtonLabel,
}: FlagSelectorProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    // Recently-used flags are persisted with just `{ name, id }` (no `key`), so a selection made
    // from the recents list can't be labeled from the picked item alone. Track the label directly
    // from whatever the picker handed us, falling back to a live lookup only until that resolves.
    const [selectedFlag, setSelectedFlag] = useState<{ id: number; label: string } | undefined>(undefined)

    const { featureFlag } = useValues(featureFlagLogic({ id: value || 'link' }))

    useEffect(() => {
        if (value === undefined || selectedFlag?.id !== value) {
            setSelectedFlag(undefined)
        }
    }, [value]) // oxlint-disable-line react-hooks/exhaustive-deps

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.FeatureFlags,
        value: value,
        onChange: (_, __, item) => {
            // Only close the popover and report a selection when the clicked item actually
            // resolved to a flag id -- otherwise we'd silently close on a no-op click, leaving
            // the user unsure whether anything happened.
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

    const buttonLabel = selectedFlag?.label || featureFlag.key || (initialButtonLabel ?? 'Select flag')

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
