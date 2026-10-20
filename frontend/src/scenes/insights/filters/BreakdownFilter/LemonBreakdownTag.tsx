import './BreakdownTag.scss'

import clsx from 'clsx'

import { IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'

import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { BreakdownTagProps } from './BreakdownTag'

export function LemonBreakdownTag({
    propertyName,
    breakdownType = 'event',
    disablePropertyInfo,
    onClose,
    onClick,
    popover,
    size = 'medium',
}: Omit<BreakdownTagProps, 'breakdown'> & { propertyName: string | number }): JSX.Element {
    const clickable = onClick !== undefined
    const closeable = onClose !== undefined
    const ButtonComponent = clickable ? 'button' : 'div'

    return (
        <ButtonComponent
            className={clsx('BreakdownTag', `BreakdownTag--${size}`, {
                'BreakdownTag--clickable': clickable,
            })}
            data-attr="breakdown-tag"
            type={ButtonComponent === 'button' ? 'button' : undefined}
            title={String(propertyName)}
            onClick={onClick}
        >
            {breakdownType === 'hogql' ? (
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
            )}
            {popover?.overlay && (
                <LemonButtonWithDropdown
                    size="xsmall"
                    icon={<IconEllipsis />}
                    onClick={(e) => {
                        e.stopPropagation()
                    }}
                    dropdown={popover}
                    className="p-0.5"
                    data-attr="breakdown-tag-options"
                />
            )}

            {closeable && (
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={(e) => {
                        e.stopPropagation()
                        onClose()
                    }}
                    className="p-0.5"
                    data-attr="breakdown-tag-close"
                />
            )}
        </ButtonComponent>
    )
}
