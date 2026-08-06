import './PropertyKeyInfo.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useState } from 'react'

import { LemonDivider, TooltipProps } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { Popover } from 'lib/lemon-ui/Popover'
import { pluralize } from 'lib/utils/strings'
import { surveyQuestionLabelsLogic } from 'scenes/surveys/surveyQuestionLabelsLogic'

import { PropertyKey, getCoreFilterDefinition } from '~/taxonomy/helpers'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

const SURVEY_RESPONSE_PREFIX = '$survey_response_'

function SourceLogo({ source }: { source: 'posthog' | 'langfuse' }): JSX.Element {
    if (source === 'posthog') {
        // The brand logomark handles light/dark itself (gradient mark in light, white mono in dark)
        return <Logomark className="PropertyKeyInfo__logo PropertyKeyInfo__logo--posthog" />
    }
    return <span className="PropertyKeyInfo__logo PropertyKeyInfo__logo--langfuse" />
}

export interface PropertyKeyInfoProps {
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

const PropertyKeyInfoBase = React.forwardRef<HTMLSpanElement, PropertyKeyInfoProps>(function PropertyKeyInfoBase(
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

    value = value?.toString() ?? ''

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
            {recognizedSource && !disableIcon && <SourceLogo source={recognizedSource} />}
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
                        {recognizedSource && <SourceLogo source={recognizedSource} />}
                        {coreDefinition.label}
                    </div>
                    {coreDefinition.description || coreDefinition.examples ? (
                        <>
                            <LemonDivider className="my-3" />
                            <div>
                                {coreDefinition.description ? <p>{coreDefinition.description}</p> : null}
                                {coreDefinition.examples ? (
                                    <p>
                                        <i>
                                            Example{' '}
                                            {pluralize(coreDefinition.examples.length, 'value', 'values', false)}:{' '}
                                        </i>
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

// Mounted only when the value is a `$survey_response_<question-id>` key. Two
// jobs: (1) trigger the `surveyQuestionLabelsLogic` mount so its `afterMount`
// fires the slim labels endpoint, and (2) subscribe to the resulting state so
// this component re-renders when the labels land, picking up the enriched
// label via `getCoreFilterDefinition`. The enrichment itself lives in the
// helper so non-React consumers (popovers, chart legends, definitions admin
// page) benefit too.
const PropertyKeyInfoWithSurveyMount = React.forwardRef<HTMLSpanElement, PropertyKeyInfoProps>(
    function PropertyKeyInfoWithSurveyMount(props, ref): JSX.Element {
        useValues(surveyQuestionLabelsLogic)
        return <PropertyKeyInfoBase {...props} ref={ref} />
    }
)

export const PropertyKeyInfo = React.forwardRef<HTMLSpanElement, PropertyKeyInfoProps>(
    function PropertyKeyInfo(props, ref): JSX.Element {
        const value = props.value?.toString() ?? ''
        if (value.startsWith(SURVEY_RESPONSE_PREFIX)) {
            return <PropertyKeyInfoWithSurveyMount {...props} ref={ref} />
        }
        return <PropertyKeyInfoBase {...props} ref={ref} />
    }
)
