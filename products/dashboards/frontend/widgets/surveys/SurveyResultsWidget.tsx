import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { MicrophoneHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { StackedBar, type StackedBarSegment } from 'scenes/surveys/components/StackedBar'
import { urls } from 'scenes/urls'

import { SurveyEventName, type SurveyRates, type SurveyStats } from '~/types'

import type { SurveyResponseAnswerApi, SurveyResponseRowApi } from 'products/surveys/frontend/generated/api.schemas'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { SurveyPickerSelect } from './SurveyPickerSelect'
import { patchSurveyResultsWidgetConfig } from './surveysWidgetConfigValidation'

// Reuse the survey responses API types (SurveyResponseRowApi / SurveyResponseAnswerApi) rather than
// redeclaring them. The widget payload is a strict subset: it drops question_index and the extra
// metadata block, and adds a resolved person display name.
export type SurveyResultsWidgetResponseAnswer = Omit<SurveyResponseAnswerApi, 'question_index'>

export type SurveyResultsWidgetResponse = Pick<SurveyResponseRowApi, 'uuid' | 'distinct_id' | 'session_id'> & {
    person_display_name: string | null
    submitted_at: string | null
    answers: SurveyResultsWidgetResponseAnswer[]
}

export type SurveyResultsWidgetResult = {
    survey: {
        id: string
        name: string
        type: string
        archived: boolean
        start_date: string | null
        end_date: string | null
    } | null
    stats?: SurveyStats
    rates?: SurveyRates
    responses: SurveyResultsWidgetResponse[]
    hasMore?: boolean
    needsConfiguration?: boolean
    surveyNotFound?: boolean
    hasSurveys?: boolean
}

type SurveyStatus = 'draft' | 'active' | 'ended' | 'archived'

function surveyStatus(survey: NonNullable<SurveyResultsWidgetResult['survey']>): SurveyStatus {
    if (survey.archived) {
        return 'archived'
    }
    if (!survey.start_date) {
        return 'draft'
    }
    return survey.end_date ? 'ended' : 'active'
}

const STATUS_TAG: Record<SurveyStatus, { label: string; type: 'success' | 'default' | 'danger' }> = {
    active: { label: 'Active', type: 'success' },
    draft: { label: 'Draft', type: 'default' },
    ended: { label: 'Ended', type: 'danger' },
    archived: { label: 'Archived', type: 'default' },
}

function formatAnswer(answer: unknown): string {
    if (answer == null) {
        return ''
    }
    // Multi-select answers can arrive as a JSON-encoded array string (e.g. `["a","b"]`); decode it.
    let value = answer
    if (typeof value === 'string' && value.trim().startsWith('[')) {
        try {
            value = JSON.parse(value)
        } catch {
            // Not JSON, show the string as-is.
        }
    }
    return Array.isArray(value) ? value.map((item) => String(item)).join(', ') : String(value)
}

function captureCreateSurveyClicked(tileId: number): void {
    posthog.capture('dashboard widget create survey clicked', { widget_type: 'survey_results', tile_id: tileId })
}

function SurveyResultsWidgetMessage({
    title,
    message,
    cta,
}: {
    title: string
    message: string
    cta?: JSX.Element
}): JSX.Element {
    return (
        <WidgetCardContent>
            <WidgetCardBodyMessage>
                <div
                    className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                    data-attr="survey-results-widget-message"
                >
                    <MicrophoneHog className="size-24 shrink-0" />
                    <p className="m-0 text-base font-semibold text-primary">{title}</p>
                    <p className="m-0 text-sm text-muted">{message}</p>
                    {cta}
                </div>
            </WidgetCardBodyMessage>
        </WidgetCardContent>
    )
}

function SurveyStatsSummary({ stats, rates }: { stats: SurveyStats; rates: SurveyRates }): JSX.Element {
    const shown = stats[SurveyEventName.SHOWN].total_count
    const sent = stats[SurveyEventName.SENT].total_count
    const dismissed = stats[SurveyEventName.DISMISSED].total_count
    const onlySeen = stats[SurveyEventName.SHOWN].total_count_only_seen

    const segments: StackedBarSegment[] = [
        { count: sent, label: 'Submitted', colorClass: 'bg-success' },
        { count: dismissed, label: 'Dismissed', colorClass: 'bg-warning' },
        { count: onlySeen, label: 'Unanswered', colorClass: 'bg-brand-blue' },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-stretch overflow-x-auto rounded border bg-bg-light/40">
                {[
                    { title: 'Shown', value: humanFriendlyNumber(shown), valueClass: 'text-primary' },
                    { title: 'Responses', value: humanFriendlyNumber(sent), valueClass: 'text-success' },
                    {
                        title: 'Conversion',
                        value: `${humanFriendlyNumber(rates.response_rate)}%`,
                        valueClass: 'text-primary',
                    },
                ].map((item, index) => (
                    <div
                        key={item.title}
                        className={`flex min-w-[6rem] flex-1 flex-col items-center px-2 py-1.5 text-center ${
                            index > 0 ? 'border-l border-border' : ''
                        }`}
                    >
                        <div className="text-2xs font-semibold uppercase tracking-wide text-muted">{item.title}</div>
                        <div className={`text-lg font-semibold leading-tight ${item.valueClass}`}>{item.value}</div>
                    </div>
                ))}
            </div>
            {shown > 0 ? <StackedBar segments={segments} size="sm" /> : null}
        </div>
    )
}

function SurveyResponseRow({ response }: { response: SurveyResultsWidgetResponse }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 rounded border p-2">
            <div className="flex items-center justify-between gap-2 text-xs text-muted">
                {/* PersonDisplay has no target prop, so wrap it to open the profile in a new tab. */}
                <Link
                    to={urls.personByDistinctId(response.distinct_id)}
                    target="_blank"
                    className="min-w-0 truncate font-medium text-primary"
                >
                    <PersonDisplay
                        person={{ distinct_id: response.distinct_id, properties: {} }}
                        displayName={response.person_display_name ?? undefined}
                        withIcon
                        noPopover
                        noLink
                    />
                </Link>
                {response.submitted_at ? <TZLabel time={response.submitted_at} /> : null}
            </div>
            {response.answers.map((answer) => {
                const formatted = formatAnswer(answer.answer)
                if (!formatted) {
                    return null
                }
                return (
                    <div key={answer.question_id} className="flex flex-col">
                        <span className="text-xs text-muted">Q: {answer.question_text}</span>
                        <span className="text-sm text-primary">{formatted}</span>
                    </div>
                )
            })}
        </div>
    )
}

function SurveyResultsLoadingSkeleton(): JSX.Element {
    return (
        <WidgetCardContent>
            <div className="flex flex-col gap-3 p-2" aria-busy aria-label="Loading survey results">
                <div className="flex items-center justify-between gap-2" aria-hidden>
                    <LemonSkeleton className="h-4 w-1/3 max-w-xs" />
                    <LemonSkeleton className="h-5 w-16 rounded" />
                </div>
                <LemonSkeleton className="h-12 w-full rounded" aria-hidden />
                <div className="flex flex-col gap-2" aria-hidden>
                    {Array.from({ length: 3 }, (_, index) => (
                        <LemonSkeleton key={index} className="h-12 w-full rounded" />
                    ))}
                </div>
            </div>
        </WidgetCardContent>
    )
}

// Editable tile with no survey chosen yet: owns the optimistic pick so the selection shows
// immediately rather than waiting for the persist + refresh round-trip.
function SurveyResultsEmptyStatePicker({
    tileId,
    config,
    onUpdateConfig,
}: Required<Pick<DashboardWidgetComponentProps, 'tileId' | 'config' | 'onUpdateConfig'>>): JSX.Element {
    const [optimisticSurveyId, setOptimisticSurveyId] = useState<string | null>(null)
    return (
        <div className="w-64 max-w-full">
            <SurveyPickerSelect
                pickerKey={`results-tile-${tileId}`}
                value={optimisticSurveyId}
                fullWidth
                onChange={async (value) => {
                    setOptimisticSurveyId(value)
                    try {
                        await onUpdateConfig(patchSurveyResultsWidgetConfig(config, value))
                    } catch {
                        // Persist failed, drop the optimistic pick so we don't show a selection that wasn't saved.
                        setOptimisticSurveyId((current) => (current === value ? null : current))
                    }
                }}
                onCreateNew={() => captureCreateSurveyClicked(tileId)}
                dataAttr="survey-results-widget-empty-state-select"
            />
        </div>
    )
}

function SurveyResultsContent({
    tileId,
    survey,
    responses,
    stats,
    rates,
    hasMore,
}: {
    tileId: number
    survey: NonNullable<SurveyResultsWidgetResult['survey']>
    responses: SurveyResultsWidgetResponse[]
    stats?: SurveyStats
    rates?: SurveyRates
    hasMore?: boolean
}): JSX.Element {
    const tag = STATUS_TAG[surveyStatus(survey)]
    return (
        <WidgetCardContent>
            <div className="flex flex-col gap-3 p-2" data-attr="survey-results-widget-body">
                <div className="flex items-center justify-between gap-2">
                    <Link
                        to={urls.survey(survey.id)}
                        target="_blank"
                        className="text-sm font-medium"
                        onClick={() =>
                            posthog.capture('dashboard widget open survey clicked', {
                                widget_type: 'survey_results',
                                tile_id: tileId,
                                survey_id: survey.id,
                            })
                        }
                    >
                        See more
                    </Link>
                    <LemonTag type={tag.type}>{tag.label}</LemonTag>
                </div>
                {stats && rates ? <SurveyStatsSummary stats={stats} rates={rates} /> : null}
                <div className="flex flex-col gap-2">
                    <h5 className="m-0 text-2xs font-semibold uppercase tracking-wide text-muted">Recent responses</h5>
                    {responses.length === 0 ? (
                        <span className="text-sm text-muted">No responses to show yet.</span>
                    ) : (
                        responses.map((response) => <SurveyResponseRow key={response.uuid} response={response} />)
                    )}
                    {hasMore ? (
                        <Link to={urls.survey(survey.id)} target="_blank" className="text-xs text-muted">
                            Open the survey to see all responses.
                        </Link>
                    ) : null}
                </div>
            </div>
        </WidgetCardContent>
    )
}

export function SurveyResultsWidget({
    tileId,
    config,
    result,
    loading,
    onUpdateConfig,
}: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as SurveyResultsWidgetResult | null | undefined

    if (loading) {
        return <SurveyResultsLoadingSkeleton />
    }

    if (!payload || payload.needsConfiguration) {
        // No surveys in the project yet: mirror the list widget's "create one" CTA.
        if (onUpdateConfig && payload && payload.hasSurveys === false) {
            return (
                <SurveyResultsWidgetMessage
                    title="No surveys yet"
                    message="Create a survey to start collecting feedback from your users."
                    cta={
                        <LemonButton
                            type="primary"
                            size="small"
                            to={urls.surveys()}
                            targetBlank
                            onClick={() => captureCreateSurveyClicked(tileId)}
                        >
                            New survey
                        </LemonButton>
                    }
                />
            )
        }
        return (
            <SurveyResultsWidgetMessage
                title="No survey selected"
                message={
                    onUpdateConfig
                        ? 'Pick a survey to see its performance and recent responses here.'
                        : 'No survey has been selected for this tile yet.'
                }
                cta={
                    onUpdateConfig ? (
                        <SurveyResultsEmptyStatePicker
                            tileId={tileId}
                            config={config}
                            onUpdateConfig={onUpdateConfig}
                        />
                    ) : undefined
                }
            />
        )
    }

    if (payload.surveyNotFound || !payload.survey) {
        return (
            <SurveyResultsWidgetMessage
                title="Survey not found"
                message="This survey may have been deleted. Pick another one in the widget settings."
            />
        )
    }

    return (
        <SurveyResultsContent
            tileId={tileId}
            survey={payload.survey}
            responses={payload.responses}
            stats={payload.stats}
            rates={payload.rates}
            hasMore={payload.hasMore}
        />
    )
}
