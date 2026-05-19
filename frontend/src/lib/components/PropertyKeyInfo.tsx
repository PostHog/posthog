import './PropertyKeyInfo.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useState } from 'react'

import { LemonDivider, TooltipProps } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { pluralize } from 'lib/utils'
import { SurveyQuestionLabel, surveyQuestionLabelsLogic } from 'scenes/surveys/surveyQuestionLabelsLogic'

import { PropertyKey, getCoreFilterDefinition } from '~/taxonomy/helpers'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

const SURVEY_RESPONSE_PREFIX = '$survey_response_'

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

interface PropertyKeyInfoBaseProps extends PropertyKeyInfoProps {
    resolvedSurveyQuestion: SurveyQuestionLabel | null
}

const PropertyKeyInfoBase = React.forwardRef<HTMLSpanElement, PropertyKeyInfoBaseProps>(function PropertyKeyInfoBase(
    {
        value,
        type = TaxonomicFilterGroupType.EventProperties,
        disablePopover = false,
        disableIcon = false,
        ellipsis = true,
        className = '',
        displayText,
        resolvedSurveyQuestion,
    },
    ref
): JSX.Element {
    const [popoverVisible, setPopoverVisible] = useState(false)

    value = value?.toString() ?? ''

    const coreDefinition = getCoreFilterDefinition(value, type)

    const enrichedCoreDefinition =
        resolvedSurveyQuestion && coreDefinition
            ? {
                  ...coreDefinition,
                  label: `${resolvedSurveyQuestion.questionText} · ${resolvedSurveyQuestion.surveyName}`,
                  description: `Response to "${resolvedSurveyQuestion.questionText}" in survey "${resolvedSurveyQuestion.surveyName}".`,
              }
            : coreDefinition

    const valueDisplayText =
        displayText || ((enrichedCoreDefinition ? enrichedCoreDefinition.label : value)?.trim() ?? '')
    const valueDisplayElement = valueDisplayText === '' ? <i>(empty string)</i> : valueDisplayText

    const recognizedSource: 'posthog' | 'langfuse' | null =
        enrichedCoreDefinition || value.startsWith('$') ? 'posthog' : value.startsWith('langfuse ') ? 'langfuse' : null

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

    return !enrichedCoreDefinition || disablePopover ? (
        innerContent
    ) : (
        <Popover
            className={className}
            overlay={
                <div className="PropertyKeyInfo__overlay">
                    <div className="PropertyKeyInfo__header">
                        {!!enrichedCoreDefinition && (
                            <span className={`PropertyKeyInfo__logo PropertyKeyInfo__logo--${recognizedSource}`} />
                        )}
                        {enrichedCoreDefinition.label}
                    </div>
                    {enrichedCoreDefinition.description || enrichedCoreDefinition.examples ? (
                        <>
                            <LemonDivider className="my-3" />
                            <div>
                                {enrichedCoreDefinition.description ? (
                                    <p>{enrichedCoreDefinition.description}</p>
                                ) : null}
                                {enrichedCoreDefinition.examples ? (
                                    <p>
                                        <i>
                                            Example{' '}
                                            {pluralize(
                                                enrichedCoreDefinition.examples.length,
                                                'value',
                                                'values',
                                                false
                                            )}
                                            :{' '}
                                        </i>
                                        {enrichedCoreDefinition.examples.join(', ')}
                                    </p>
                                ) : null}
                            </div>
                        </>
                    ) : null}

                    {!enrichedCoreDefinition.virtual && (
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

// Mounted only when the value is a `$survey_response_<question-id>` key. This is the only
// place where `surveyQuestionLabelsLogic` is touched, so the survey-labels fetch is paid for
// exactly when the page actually renders a survey response property, not on every
// `PropertyKeyInfo` instance across the app.
const PropertyKeyInfoWithSurveyResolution = React.forwardRef<HTMLSpanElement, PropertyKeyInfoProps>(
    function PropertyKeyInfoWithSurveyResolution(props, ref): JSX.Element {
        const { surveyQuestionLabels } = useValues(surveyQuestionLabelsLogic)
        const questionId = (props.value?.toString() ?? '').slice(SURVEY_RESPONSE_PREFIX.length)
        return (
            <PropertyKeyInfoBase
                {...props}
                resolvedSurveyQuestion={surveyQuestionLabels[questionId] ?? null}
                ref={ref}
            />
        )
    }
)

export const PropertyKeyInfo = React.forwardRef<HTMLSpanElement, PropertyKeyInfoProps>(
    function PropertyKeyInfo(props, ref): JSX.Element {
        const value = props.value?.toString() ?? ''
        if (value.startsWith(SURVEY_RESPONSE_PREFIX)) {
            return <PropertyKeyInfoWithSurveyResolution {...props} ref={ref} />
        }
        return <PropertyKeyInfoBase {...props} resolvedSurveyQuestion={null} ref={ref} />
    }
)
