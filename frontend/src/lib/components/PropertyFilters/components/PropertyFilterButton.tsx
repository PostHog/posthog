import './PropertyFilterButton.scss'

import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { CloseButton } from 'lib/components/CloseButton'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconClose } from 'lib/lemon-ui/icons'
import { KEY_MAPPING } from 'lib/taxonomy'
import { midEllipsis } from 'lib/utils'
import React from 'react'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter } from '~/types'

import { formatPropertyLabel } from '../utils'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
}

export const PropertyFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton({ onClick, onClose, children, item }, ref): JSX.Element {
        const { cohortsById } = useValues(cohortsModel)
        const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
        const is3000 = useFeatureFlag('POSTHOG_3000', 'test')

        const closable = onClose !== undefined
        const clickable = onClick !== undefined
        const label =
            children ||
            formatPropertyLabel(
                item,
                cohortsById,
                KEY_MAPPING,
                (s) => formatPropertyValueForDisplay(item.key, s)?.toString() || '?'
            )

        const ButtonComponent = clickable ? 'button' : 'div'

        return (
            <ButtonComponent
                ref={ref as any}
                onClick={onClick}
                className={clsx('PropertyFilterButton', {
                    'PropertyFilterButton--closeable': closable,
                    'PropertyFilterButton--clickable': clickable,
                    'ph-no-capture': true,
                })}
            >
                <PropertyFilterIcon type={item.type} />
                <span className="PropertyFilterButton-content" title={label}>
                    {midEllipsis(label, 32)}
                </span>
                {closable && (
                    <>
                        {is3000 ? (
                            <LemonButton
                                size="xsmall"
                                icon={<IconClose />}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onClose()
                                }}
                                stealth
                                className="p-0.5"
                                status="stealth"
                            />
                        ) : (
                            <CloseButton
                                onClick={(e: MouseEvent) => {
                                    e.stopPropagation()
                                    onClose()
                                }}
                            />
                        )}
                    </>
                )}
            </ButtonComponent>
        )
    }
)
