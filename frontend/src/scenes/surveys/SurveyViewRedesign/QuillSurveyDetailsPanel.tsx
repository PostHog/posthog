import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCode } from '@posthog/icons'
import { Button, Heading, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    COPY_SURVEY_EMBED_CODE_TOOLTIP,
    COPY_SURVEY_URL_TOOLTIP,
    copySurveyEmbedCode,
    copySurveyUrl,
} from 'scenes/surveys/CopySurveyLink'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getNextPreviewPageIndex } from 'scenes/surveys/surveyPreviewNavigation'
import { clampPreviewPageIndex, getSurveyDisplayConditionsSummary } from 'scenes/surveys/utils'

import { Survey, SurveyType } from '~/types'

import { SURVEY_CONDITION_ICON } from '../components/SurveyConditions'
import { SURVEY_API_DOCS_URL, getSurveyAtAGlanceRows, getSurveyPreviewPageOptions } from './SurveySidebar'

function DetailsSection({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 />} className="m-0">
                {title}
            </Heading>
            {children}
        </section>
    )
}

export function QuillSurveyDetailsPanel(): JSX.Element {
    const { survey, selectedPageIndex, hasTargetingSet } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const effectivePageIndex = clampPreviewPageIndex(selectedPageIndex, survey)
    const pageOptions = getSurveyPreviewPageOptions(survey)
    const conditionsSummary = hasTargetingSet ? getSurveyDisplayConditionsSummary(survey as Survey) : []

    return (
        <div className="flex flex-col gap-6">
            {survey.type !== SurveyType.API && (
                <DetailsSection title="Preview">
                    <div className="flex justify-center">
                        <SurveyAppearancePreview
                            survey={survey as Survey}
                            previewPageIndex={effectivePageIndex}
                            onPreviewSubmit={(response) => {
                                const nextPageIndex = getNextPreviewPageIndex(survey, effectivePageIndex, response)
                                if (nextPageIndex !== null) {
                                    setSelectedPageIndex(nextPageIndex)
                                }
                            }}
                        />
                    </div>
                    <Select
                        value={effectivePageIndex}
                        onValueChange={(pageIndex) => setSelectedPageIndex(pageIndex as number)}
                    >
                        <SelectTrigger
                            aria-label="Preview page"
                            className="w-full min-w-0"
                            data-attr="survey-details-preview-page"
                        >
                            <SelectValue className="truncate">
                                {(pageIndex: number) => pageOptions.find((option) => option.value === pageIndex)?.label}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {pageOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </DetailsSection>
            )}

            <DetailsSection title="At a glance">
                <dl className="m-0 flex flex-col gap-1.5">
                    {getSurveyAtAGlanceRows(survey as Survey, hasTargetingSet).map((row) => (
                        <div key={row.key} className="flex items-baseline justify-between gap-4">
                            <Text size="xs" variant="muted" render={<dt />} className="m-0 shrink-0">
                                {row.label}
                            </Text>
                            <Text size="xs" render={<dd />} className="m-0 min-w-0 truncate text-right">
                                {row.value}
                            </Text>
                        </div>
                    ))}
                </dl>
                {survey.type === SurveyType.ExternalSurvey && (
                    <div className="flex flex-wrap gap-2">
                        <Button
                            variant="outline"
                            tooltip={COPY_SURVEY_URL_TOOLTIP}
                            onClick={() => copySurveyUrl(survey.id)}
                            data-attr="survey-details-copy-url"
                        >
                            <IconLink />
                            Copy URL
                        </Button>
                        {survey.enable_iframe_embedding && (
                            <Button
                                variant="outline"
                                tooltip={COPY_SURVEY_EMBED_CODE_TOOLTIP}
                                onClick={() => copySurveyEmbedCode(survey.id)}
                                data-attr="survey-details-copy-embed-code"
                            >
                                <IconCode />
                                Copy embed code
                            </Button>
                        )}
                    </div>
                )}
                {survey.type === SurveyType.API && (
                    <Text size="xs" className="m-0">
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={SURVEY_API_DOCS_URL} target="_blank" />}
                        >
                            View API docs
                        </Button>
                    </Text>
                )}
            </DetailsSection>

            {conditionsSummary.length > 0 && (
                <DetailsSection title="Display conditions">
                    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                        {conditionsSummary.map(({ type, label, value, href }) => {
                            const Icon = SURVEY_CONDITION_ICON[type]
                            return (
                                <li key={type} className="flex items-center gap-2">
                                    <Icon className="shrink-0 text-muted-foreground" />
                                    <Text size="xs" variant="muted" render={<span />} className="whitespace-nowrap">
                                        {label}
                                    </Text>
                                    <Text size="xs" render={<span />} className="ml-auto min-w-0 truncate text-right">
                                        {href ? (
                                            <Button
                                                variant="link"
                                                size="inline"
                                                nativeButton={false}
                                                render={<LinkPrimitive to={href} />}
                                            >
                                                {value}
                                            </Button>
                                        ) : (
                                            value
                                        )}
                                    </Text>
                                </li>
                            )
                        })}
                    </ul>
                </DetailsSection>
            )}
        </div>
    )
}
