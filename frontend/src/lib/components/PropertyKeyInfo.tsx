import './PropertyKeyInfo.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useState } from 'react'

import { LemonDivider, TooltipProps } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { Popover } from 'lib/lemon-ui/Popover'
import { pluralize } from 'lib/utils/strings'
import { surveyQuestionLabelsLogic } from 'scenes/surveys/surveyQuestionLabelsLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyKey, getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CoreFilterDefinition, PropertyDefinitionType } from '~/types'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

const SURVEY_RESPONSE_PREFIX = '$survey_response_'

/** Maps the taxonomic group types that carry a corresponding `propertyDefinitionsModel` type, so
 * non-taxonomy (custom) property keys can still resolve a definition from the team's own metadata. */
const TAXONOMIC_GROUP_TYPE_TO_PROPERTY_DEFINITION_TYPE: Partial<
    Record<TaxonomicFilterGroupType, PropertyDefinitionType>
> = {
    [TaxonomicFilterGroupType.EventProperties]: PropertyDefinitionType.Event,
    [TaxonomicFilterGroupType.PersonProperties]: PropertyDefinitionType.Person,
    [TaxonomicFilterGroupType.EventMetadata]: PropertyDefinitionType.EventMetadata,
    [TaxonomicFilterGroupType.PersonMetadata]: PropertyDefinitionType.PersonMetadata,
    [TaxonomicFilterGroupType.SessionProperties]: PropertyDefinitionType.Session,
}
const GROUP_TAXONOMIC_TYPE_REGEX = /^groups_(\d+)$/

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

    const groupMatch = type.match(GROUP_TAXONOMIC_TYPE_REGEX)
    const propertyDefinitionType = groupMatch
        ? PropertyDefinitionType.Group
        : TAXONOMIC_GROUP_TYPE_TO_PROPERTY_DEFINITION_TYPE[type]
    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)
    const customPropertyDefinition =
        !coreDefinition && propertyDefinitionType
            ? getPropertyDefinition(value, propertyDefinitionType, groupMatch ? Number(groupMatch[1]) : undefined)
            : null
    const customDefinition: CoreFilterDefinition | null = customPropertyDefinition
        ? { label: customPropertyDefinition.name, description: customPropertyDefinition.description }
        : null
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
