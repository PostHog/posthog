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
}

export function FlagSelector({ value, onChange, readOnly, disabledReason }: FlagSelectorProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    const { featureFlag } = useValues(featureFlagLogic({ id: value || 'link' }))

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.FeatureFlags,
        value: value,
        onChange: (_, __, item) => {
            'id' in item && item.id && onChange(item.id, item.key, item)
            setVisible(false)
        },
        taxonomicGroupTypes: [TaxonomicFilterGroupType.FeatureFlags],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
        taxonomicFilterLogicKey: 'flag-selectorz',
    }

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
                {featureFlag.key ? featureFlag.key : 'Select flag'}
            </LemonButton>
        </Popover>
    )
}
