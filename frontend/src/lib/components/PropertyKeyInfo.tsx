import './PropertyKeyInfo.scss'

import clsx from 'clsx'
import React, { useState } from 'react'

import { LemonDivider, TooltipProps } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { PropertyKey, getCoreFilterDefinition } from '~/taxonomy/helpers'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

interface PropertyKeyInfoProps {
    value: PropertyKey
    type?: TaxonomicFilterGroupType
    displayText?: string
    tooltipPlacement?: TooltipProps['placement']
    disablePopover?: boolean
    disableIcon?: boolean
    /** @default true */
    ellipsis?: boolean
    className?: string
}

export const PropertyKeyInfo = React.forwardRef<HTMLSpanElement, PropertyKeyInfoProps>(function PropertyKeyInfo(
    {
        value,
        type = TaxonomicFilterGroupType.EventProperties,
        disablePopover = false,
        disableIcon = false,
        ellipsis = true,
        className = '',
        displayText,
    },
    ref
): JSX.Element {
    const [popoverVisible, setPopoverVisible] = useState(false)

    value = value?.toString() ?? '' // convert to string

    const coreDefinition = getCoreFilterDefinition(value, type)
    const valueDisplayText = displayText || ((coreDefinition ? coreDefinition.label : value)?.trim() ?? '')
    const valueDisplayElement = valueDisplayText === '' ? <i>(empty string)</i> : valueDisplayText

    const recognizedSource: 'posthog' | 'langfuse' | null =
        coreDefinition || value.startsWith('$') ? 'posthog' : value.startsWith('langfuse ') ? 'langfuse' : null

    const innerContent = (
        <span
            className={clsx('PropertyKeyInfo', className)}
            aria-label={valueDisplayText}
            title={ellipsis && disablePopover ? valueDisplayText : undefined}
            ref={ref}
        >
            {recognizedSource && !disableIcon && (
                <span className={`PropertyKeyInfo__logo PropertyKeyInfo__logo--${recognizedSource}`} />
            )}
            <span className={clsx('PropertyKeyInfo__text', ellipsis && 'PropertyKeyInfo__text--ellipsis')}>
                {valueDisplayElement}
            </span>
        </span>
    )

    return !coreDefinition || disablePopover ? (
        innerContent
    ) : (
        <Popover
            className={className}
            overlay={
                <div className="PropertyKeyInfo__overlay">
                    <div className="PropertyKeyInfo__header">
                        {!!coreDefinition && (
                            <span className={`PropertyKeyInfo__logo PropertyKeyInfo__logo--${recognizedSource}`} />
                        )}
                        {coreDefinition.label}
                    </div>
                    {coreDefinition.description || coreDefinition.examples ? (
                        <>
                            <LemonDivider className="my-3" />
                            <div>
                                {coreDefinition.description ? <p>{coreDefinition.description}</p> : null}
                                {coreDefinition.examples ? (
                                    <p>
                                        <i>Example value{coreDefinition.examples.length === 1 ? '' : 's'}: </i>
                                        {coreDefinition.examples.join(', ')}
                                    </p>
                                ) : null}
                            </div>
                        </>
                    ) : null}

                    {!coreDefinition.virtual && (
                        <>
                            <LemonDivider className="my-3" />
                            <div>
                                Sent as <code>{value}</code>
                            </div>
                        </>
                    )}
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
})
