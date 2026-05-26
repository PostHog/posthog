import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconCode, IconGlobe, IconLaptop, IconPin } from '@posthog/icons'
import { LemonDivider, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { ViewRecordingButtonVariant } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconLink } from 'lib/lemon-ui/icons'
import { countryCodeToFlag } from 'lib/utils/geography/country'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { getThumbIcon } from 'scenes/surveys/hooks/useSurveyResponseColumns'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyResponseValue, isScaleTwoRating } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { SurveyEventProperties as SurveyEventPropertyNames, SurveyQuestion } from '~/types'

interface SurveyResponseDisplayProps {
    eventProperties: Record<string, any>
    eventUuid?: string
    distinctId?: string
    timestamp?: string | null
    personProperties?: Record<string, any>
}

function prettyUrl(url: string): string {
    try {
        const parsed = new URL(url)
        return `${parsed.host}${parsed.pathname}`.replace(/\/$/, '') || parsed.host
    } catch {
        return url.replace(/^https?:\/\//, '')
    }
}

function formatAnswer(value: unknown): string {
    if (Array.isArray(value)) {
        return value.join(', ')
    }
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

function AnswerDisplay({ question, value }: { question: SurveyQuestion; value: unknown }): JSX.Element {
    if (isScaleTwoRating(question) && (value == '1' || value == '2')) {
        return (
            <span className="text-sm font-medium flex items-center gap-1.5">
                {getThumbIcon(value)}
                Thumbs {value == '1' ? 'up' : 'down'}
            </span>
        )
    }
    return (
        <p className="text-sm font-medium text-default whitespace-pre-wrap leading-relaxed m-0 break-words">
            {formatAnswer(value)}
        </p>
    )
}

function MetaItem({ icon, children }: { icon?: JSX.Element; children: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1 min-w-0">
            {icon && <span className="shrink-0 flex items-center text-muted">{icon}</span>}
            <span className="truncate">{children}</span>
        </span>
    )
}

export function SurveyResponseDisplay({
    eventProperties,
    eventUuid,
    distinctId,
    timestamp,
    personProperties,
}: SurveyResponseDisplayProps): JSX.Element {
    const surveyId = eventProperties[SurveyEventPropertyNames.SURVEY_ID]

    const { location } = useValues(router)
    const isOnSurveyPage = surveyId && location.pathname.includes(`/surveys/${surveyId}`)

    const { survey, archivedResponseUuids } = useValues(surveyLogic({ id: surveyId }))
    const isArchived = eventUuid ? (archivedResponseUuids?.has(eventUuid) ?? false) : false

    const surveyName = survey?.name || eventProperties['$survey_name']
    const iteration = eventProperties[SurveyEventPropertyNames.SURVEY_ITERATION]
    const isPartial =
        eventProperties[SurveyEventPropertyNames.SURVEY_COMPLETED] === false ||
        eventProperties[SurveyEventPropertyNames.SURVEY_PARTIALLY_COMPLETED] === true

    const sessionId = typeof eventProperties.$session_id === 'string' ? eventProperties.$session_id : undefined
    const currentUrl = typeof eventProperties.$current_url === 'string' ? eventProperties.$current_url : null
    const browser = typeof eventProperties.$browser === 'string' ? eventProperties.$browser : null
    const os = typeof eventProperties.$os === 'string' ? eventProperties.$os : null
    const deviceType = typeof eventProperties.$device_type === 'string' ? eventProperties.$device_type : null
    const deviceLine = [browser, os, deviceType].filter(Boolean).join(' · ')
    const city = typeof eventProperties.$geoip_city_name === 'string' ? eventProperties.$geoip_city_name : null
    const country = typeof eventProperties.$geoip_country_name === 'string' ? eventProperties.$geoip_country_name : null
    const countryCode =
        typeof eventProperties.$geoip_country_code === 'string' ? eventProperties.$geoip_country_code : null
    const locationLine = [city, country].filter(Boolean).join(', ')
    const lib = typeof eventProperties.$lib === 'string' ? eventProperties.$lib : null
    const libVersion = typeof eventProperties.$lib_version === 'string' ? eventProperties.$lib_version : null
    const libraryLine = [lib, libVersion].filter(Boolean).join(' ')

    const hasFooter = currentUrl || deviceLine || locationLine || libraryLine
    const hasHeaderMeta = distinctId || timestamp || sessionId || isPartial || isArchived || iteration != null

    const responses: { questionIndex: number; question: SurveyQuestion; value: any }[] = []

    if (survey?.questions) {
        survey.questions.forEach((q, index) => {
            const question = q as SurveyQuestion
            const value = getSurveyResponseValue(eventProperties, index, question.id)
            if (value !== undefined) {
                responses.push({ questionIndex: index, question, value })
            }
        })
    }

    return (
        <div className="flex flex-col gap-4 pb-2">
            <div className="flex flex-row gap-2 flex-wrap items-center">
                {surveyName && <h3 className="mb-0 mr-2">{surveyName}</h3>}
                {surveyId && !isOnSurveyPage && (
                    <Link to={urls.survey(surveyId)} className="flex items-center gap-1">
                        <IconLink className="text-sm" />
                        <span className="text-sm">View survey</span>
                    </Link>
                )}
            </div>

            {hasHeaderMeta && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-secondary min-w-0">
                    {distinctId && (
                        <PersonDisplay
                            person={{ distinct_id: distinctId, properties: personProperties }}
                            withIcon="xs"
                            noEllipsis={false}
                        />
                    )}
                    {timestamp && <TZLabel time={timestamp} />}
                    {sessionId && (
                        <ViewRecordingButton
                            sessionId={sessionId}
                            timestamp={timestamp ?? undefined}
                            variant={ViewRecordingButtonVariant.Link}
                            checkRecordingExists
                        />
                    )}
                    {isPartial && (
                        <LemonTag type="warning" size="small">
                            Partial
                        </LemonTag>
                    )}
                    {isArchived && (
                        <LemonTag type="muted" size="small" icon={<IconArchive />}>
                            Response archived
                        </LemonTag>
                    )}
                    {iteration !== undefined && iteration !== null && (
                        <MetaItem>
                            <span className="text-muted">Iteration</span> {String(iteration)}
                        </MetaItem>
                    )}
                </div>
            )}

            {responses.length > 0 && (
                <div className="flex flex-col gap-4">
                    {responses.map(({ questionIndex, question, value }) => (
                        <div key={questionIndex} className="flex flex-col gap-1 min-w-0">
                            <span className="text-xs text-secondary">{question.question}</span>
                            <AnswerDisplay question={question} value={value} />
                        </div>
                    ))}
                </div>
            )}

            {hasFooter && (
                <>
                    <LemonDivider className="my-0" />
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-secondary min-w-0">
                        {currentUrl && (
                            <Link
                                to={currentUrl}
                                target="_blank"
                                title={currentUrl}
                                className="flex items-center gap-1 max-w-xs min-w-0"
                            >
                                <IconGlobe className="shrink-0 text-muted" />
                                <span className="truncate">{prettyUrl(currentUrl)}</span>
                            </Link>
                        )}
                        {deviceLine && <MetaItem icon={<IconLaptop />}>{deviceLine}</MetaItem>}
                        {locationLine && (
                            <MetaItem icon={<IconPin />}>
                                {countryCode && <span className="mr-1">{countryCodeToFlag(countryCode)}</span>}
                                {locationLine}
                            </MetaItem>
                        )}
                        {libraryLine && <MetaItem icon={<IconCode />}>{libraryLine}</MetaItem>}
                    </div>
                </>
            )}
        </div>
    )
}
