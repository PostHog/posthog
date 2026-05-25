import { useValues } from 'kea'

import { IconArchive, IconCode, IconGlobe, IconLaptop, IconPin } from '@posthog/icons'
import { LemonDivider, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { ViewRecordingButtonVariant } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { countryCodeToFlag } from 'lib/utils/geography/country'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { getThumbIcon } from 'scenes/surveys/hooks/useSurveyResponseColumns'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyResponseValue, isScaleTwoRating } from 'scenes/surveys/utils'

import { EventType, SurveyEventProperties, SurveyQuestion } from '~/types'

function prettyUrl(url: string): string {
    try {
        const parsed = new URL(url)
        return `${parsed.host}${parsed.pathname}`.replace(/\/$/, '') || parsed.host
    } catch {
        return url.replace(/^https?:\/\//, '')
    }
}

function findEventInRow(result: unknown): EventType | null {
    if (!Array.isArray(result)) {
        return null
    }
    for (const cell of result) {
        if (
            cell &&
            typeof cell === 'object' &&
            !Array.isArray(cell) &&
            'properties' in cell &&
            typeof (cell as { properties: unknown }).properties === 'object'
        ) {
            return cell as EventType
        }
    }
    return null
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

export function SurveyResponseExpandedRow({ result }: { result: unknown }): JSX.Element | null {
    const event = findEventInRow(result)
    const { survey, archivedResponseUuids } = useValues(surveyLogic)

    if (!event) {
        return null
    }

    const properties = event.properties ?? {}
    const currentUrl = typeof properties.$current_url === 'string' ? properties.$current_url : null
    const sessionId = typeof properties.$session_id === 'string' ? properties.$session_id : undefined
    const browser = typeof properties.$browser === 'string' ? properties.$browser : null
    const os = typeof properties.$os === 'string' ? properties.$os : null
    const deviceType = typeof properties.$device_type === 'string' ? properties.$device_type : null
    const deviceLine = [browser, os, deviceType].filter(Boolean).join(' · ')
    const city = typeof properties.$geoip_city_name === 'string' ? properties.$geoip_city_name : null
    const country = typeof properties.$geoip_country_name === 'string' ? properties.$geoip_country_name : null
    const countryCode = typeof properties.$geoip_country_code === 'string' ? properties.$geoip_country_code : null
    const locationLine = [city, country].filter(Boolean).join(', ')
    const lib = typeof properties.$lib === 'string' ? properties.$lib : null
    const libVersion = typeof properties.$lib_version === 'string' ? properties.$lib_version : null
    const libraryLine = [lib, libVersion].filter(Boolean).join(' ')
    const iteration = properties[SurveyEventProperties.SURVEY_ITERATION]
    const isPartial =
        properties[SurveyEventProperties.SURVEY_COMPLETED] === false ||
        properties[SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED] === true
    const isArchived = event.uuid ? archivedResponseUuids?.has(event.uuid) : false

    const responses: { questionIndex: number; question: SurveyQuestion; value: unknown }[] = []
    if (survey?.questions) {
        survey.questions.forEach((q, index) => {
            const value = getSurveyResponseValue(properties, index, q.id)
            if (value !== undefined) {
                responses.push({ questionIndex: index, question: q, value })
            }
        })
    }

    return (
        <div className="mx-auto w-full max-w-[min(56rem,calc(100vw-2rem))] min-w-0 px-4 py-4 flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-secondary min-w-0">
                <PersonDisplay
                    person={{ distinct_id: event.distinct_id, properties: event.person?.properties }}
                    withIcon="xs"
                    noEllipsis={false}
                />
                {event.timestamp && <TZLabel time={event.timestamp} />}
                {sessionId && (
                    <ViewRecordingButton
                        sessionId={sessionId}
                        timestamp={event.timestamp}
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
                        Archived
                    </LemonTag>
                )}
                {iteration !== undefined && iteration !== null && (
                    <MetaItem>
                        <span className="text-muted">Iteration</span> {String(iteration)}
                    </MetaItem>
                )}
            </div>

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
        </div>
    )
}
