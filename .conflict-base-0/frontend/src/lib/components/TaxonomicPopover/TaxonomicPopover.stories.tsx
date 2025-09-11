import { Meta } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { cohortsModel } from '~/models/cohortsModel'

import { TaxonomicPopover, TaxonomicStringPopover } from './TaxonomicPopover'

const meta: Meta<typeof TaxonomicPopover> = {
    title: 'Filters/TaxonomicPopover',
    component: TaxonomicPopover,
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

export function TaxonomicStringPopoverOneCategory(): JSX.Element {
    useMountedLogic(cohortsModel)
    const [value, setValue] = useState<string | undefined>('$browser')

    return (
        <TaxonomicStringPopover
            groupType={TaxonomicFilterGroupType.PersonProperties}
            value={value}
            onChange={setValue}
            renderValue={(v) => <PropertyKeyInfo value={v} type={TaxonomicFilterGroupType.PersonProperties} />}
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
