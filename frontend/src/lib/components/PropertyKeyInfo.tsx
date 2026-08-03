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
import { CoreFilterDefinition } from '~/types'

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
    /**
     * Definition to fall back to when `value` isn't in the static core taxonomy, e.g. sourced from
     * the team's own `propertyDefinitionsModel` by the caller. Lets non-taxonomy (custom) property
     * keys still get a definition popover, without this component depending on that app-level model
     * itself (it's reachable from the toolbar bundle, which must not import app code).
     */
    customDefinition?: CoreFilterDefinition | null
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
        customDefinition,
    },
    ref
): JSX.Element {
    const [popoverVisible, setPopoverVisible] = useState(false)

    value = value?.toString() ?? ''

    const coreDefinition = getCoreFilterDefinition(value, type)
    const effectiveDefinition = coreDefinition || customDefinition

    const valueDisplayText = displayText || ((effectiveDefinition ? effectiveDefinition.label : value)?.trim() ?? '')
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

    return !effectiveDefinition || disablePopover ? (
        innerContent
    ) : (
        <Popover
            className={className}
            overlay={
                <div className="PropertyKeyInfo__overlay">
                    <div className="PropertyKeyInfo__header">
                        {recognizedSource && <SourceLogo source={recognizedSource} />}
                        {effectiveDefinition.label}
                    </div>
                    {effectiveDefinition.description || effectiveDefinition.examples ? (
                        <>
                            <LemonDivider className="my-3" />
                            <div>
                                {effectiveDefinition.description ? <p>{effectiveDefinition.description}</p> : null}
                                {effectiveDefinition.examples ? (
                                    <p>
                                        <i>
                                            Example{' '}
                                            {pluralize(effectiveDefinition.examples.length, 'value', 'values', false)}
                                            :{' '}
                                        </i>
                                        {effectiveDefinition.examples.join(', ')}
                                    </p>
                                ) : null}
                            </div>
                        </>
                    ) : null}

                    {!effectiveDefinition.virtual && (
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
            onClickOutside={() => setPopoverVisible(false)}
            showArrow
            placement="right"
        >
            {React.cloneElement(innerContent, {
                className: clsx(innerContent.props.className, 'cursor-pointer'),
                onClick: () => setPopoverVisible((visible) => !visible),
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
