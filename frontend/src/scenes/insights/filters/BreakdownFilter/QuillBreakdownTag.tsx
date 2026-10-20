import { Button, Chip, ChipClose } from '@posthog/quill'

import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { BreakdownType } from '~/types'

export interface QuillBreakdownTagProps {
    propertyName: string | number
    breakdownType: BreakdownType | null | undefined
    disablePropertyInfo?: boolean
    onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
    onClose?: () => void
    /** The options trigger, already wrapped in the menu it opens. */
    optionsTrigger?: React.ReactNode
}

export function QuillBreakdownTag({
    propertyName,
    breakdownType,
    disablePropertyInfo,
    onClick,
    onClose,
    optionsTrigger,
}: QuillBreakdownTagProps): JSX.Element {
    const propertyInfo =
        breakdownType === 'hogql' ? (
            <HoqQLPropertyInfo value={propertyName as string} />
        ) : (
            <PropertyKeyInfo
                value={propertyName as string}
                disablePopover={disablePropertyInfo}
                type={
                    breakdownType
                        ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdownType]
                        : TaxonomicFilterGroupType.EventProperties
                }
            />
        )

    return (
        <Chip data-attr="breakdown-tag" title={String(propertyName)} className="max-w-full">
            {onClick ? (
                <Button variant="link-muted" size="inline" className="min-w-0 truncate" onClick={onClick}>
                    {propertyInfo}
                </Button>
            ) : (
                <span className="min-w-0 truncate">{propertyInfo}</span>
            )}
            {optionsTrigger}
            {onClose ? (
                <ChipClose aria-label="Remove breakdown" data-attr="breakdown-tag-close" onClick={onClose} />
            ) : null}
        </Chip>
    )
}
