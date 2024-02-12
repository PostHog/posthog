import './PropertyKeyInfo.scss'

import { LemonDivider, TooltipProps } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover'
import { getCoreFilterDefinition, PropertyKey } from 'lib/taxonomy'
import React, { useState } from 'react'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

interface PropertyKeyInfoProps {
    value: PropertyKey
    type?: TaxonomicFilterGroupType
    tooltipPlacement?: TooltipProps['placement']
    disablePopover?: boolean
    disableIcon?: boolean
    /** @default true */
    ellipsis?: boolean
    className?: string
}

export function PropertyKeyInfo({
    value,
    type = TaxonomicFilterGroupType.EventProperties,
    disablePopover = false,
    disableIcon = false,
    ellipsis = true,
    className = '',
}: PropertyKeyInfoProps): JSX.Element {
    const [popoverVisible, setPopoverVisible] = useState(false)

    value = value?.toString() ?? '' // convert to string

    const data = getCoreFilterDefinition(value, type)
    const valueDisplayText = (data ? data.label : value)?.trim() ?? ''
    const valueDisplayElement = valueDisplayText === '' ? <i>(empty string)</i> : valueDisplayText

    const innerContent = (
        <span
            className={clsx('PropertyKeyInfo', className)}
            aria-label={valueDisplayText}
            title={ellipsis && disablePopover ? valueDisplayText : undefined}
        >
            {!disableIcon && !!data && <span className="PropertyKeyInfo__logo" />}
            <span className={clsx('PropertyKeyInfo__text', ellipsis && 'PropertyKeyInfo__text--ellipsis')}>
                {valueDisplayElement}
            </span>
        </span>
    )

    return !data || disablePopover ? (
        innerContent
    ) : (
        <Popover
            className={className}
            overlay={
                <div className="PropertyKeyInfo__overlay">
                    <div className="PropertyKeyInfo__header">
                        {!!data && <span className="PropertyKeyInfo__logo" />}
                        {data.label}
                    </div>
                    {data.description || data.examples ? (
                        <>
                            <LemonDivider className="my-3" />
                            <div>
                                {data.description ? <p>{data.description}</p> : null}
                                {data.examples ? (
                                    <p>
                                        <i>Example value{data.examples.length === 1 ? '' : 's'}: </i>
                                        {data.examples.join(', ')}
                                    </p>
                                ) : null}
                            </div>
                        </>
                    ) : null}
                    <LemonDivider className="my-3" />
                    <div>
                        Sent as <code>{value}</code>
                    </div>
                </div>
            }
            visible={popoverVisible}
            showArrow
            placement="right"
        >
            {React.cloneElement(innerContent, {
                onMouseEnter: () => setPopoverVisible(true),
                onMouseLeave: () => setPopoverVisible(false),
            })}
        </Popover>
    )
}
