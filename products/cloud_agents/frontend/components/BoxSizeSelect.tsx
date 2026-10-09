import { useValues } from 'kea'

import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import type { SizeNameEnumApi } from '../generated/api.schemas'
import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'
import { formatBoxSize, formatRate } from '../utils/pricing'

/** A select of the box sizes in the catalog. Each option shows what the box costs for one hour. */
export function BoxSizeSelect({
    value,
    onChange,
    emptyLabel,
    'data-attr': dataAttr,
}: {
    value: SizeNameEnumApi | null
    onChange: (size: SizeNameEnumApi | null) => void
    /** The label of the "no size" option, for forms where a default from elsewhere applies. Leave out to require a size. */
    emptyLabel?: string
    'data-attr'?: string
}): JSX.Element {
    const { sizes, catalogLoading } = useValues(cloudAgentsCatalogLogic)
    const options: LemonSelectOption<SizeNameEnumApi | null>[] = [
        ...(emptyLabel ? [{ value: null, label: emptyLabel }] : []),
        ...sizes.map((size) => ({
            value: size.name,
            label: `${formatBoxSize(size)} · ${formatRate(size.price_per_hour_usd)} per hour`,
        })),
    ]
    return (
        <LemonSelect
            fullWidth
            value={value}
            onChange={onChange}
            options={options}
            loading={catalogLoading}
            placeholder="Choose a box size"
            data-attr={dataAttr}
        />
    )
}
