import { useState } from 'react'
import { TaxonomicPopover, TaxonomicStringPopover } from './TaxonomicPopover'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useMountedLogic } from 'kea'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { ComponentMeta } from '@storybook/react'

export default {
    title: 'Filters/TaxonomicPopover',
    component: TaxonomicPopover,
    decorators: [taxonomicFilterMocksDecorator],
} as ComponentMeta<typeof TaxonomicPopover>

export function TaxonomicStringPopoverOneCategory(): JSX.Element {
    useMountedLogic(cohortsModel)
    const [value, setValue] = useState<string | undefined>('$browser')

    return (
        <TaxonomicStringPopover
            groupType={TaxonomicFilterGroupType.PersonProperties}
            value={value}
            onChange={setValue}
            renderValue={(v) => <PropertyKeyInfo value={v} />}
        />
    )
}

export function MultipleCategories(): JSX.Element {
    useMountedLogic(cohortsModel)
    const [value, setValue] = useState<string | number | null | undefined>(undefined)
    const [group, setGroup] = useState(TaxonomicFilterGroupType.PersonProperties)

    return (
        <TaxonomicPopover
            groupType={group}
            value={value}
            onChange={(v, g) => {
                setValue(v)
                setGroup(g)
            }}
            groupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.Cohorts,
            ]}
        />
    )
}
