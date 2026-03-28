import { useActions, useValues } from 'kea'

import { IconEye } from '@posthog/icons'
import { LemonBadge } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { joinWithUiHost } from '~/toolbar/utils'
import { Survey } from '~/types'

import { PREVIEWABLE_TYPES, STATUS_COLORS, SURVEY_TYPE_LABELS } from './constants'
import { getSurveyStatus, surveysToolbarLogic } from './surveysToolbarLogic'

export function SurveyRow({ survey }: { survey: Survey }): JSX.Element {
    const { uiHost } = useValues(toolbarConfigLogic)
    const { previewLiveSurvey } = useActions(surveysToolbarLogic)
    const status = getSurveyStatus(survey)
    const typeLabel = SURVEY_TYPE_LABELS[survey.type] ?? survey.type
    const canPreview = PREVIEWABLE_TYPES.has(survey.type)

    return (
        <div className="flex items-center gap-2 py-1.5 px-1 -mx-1 rounded hover:bg-fill-primary-hover">
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                    <Link
                        className="font-medium truncate"
                        to={joinWithUiHost(uiHost, urls.survey(survey.id))}
                        subtle
                        target="_blank"
                    >
                        {survey.name}
                        <IconOpenInNew className="ml-0.5" />
                    </Link>
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-xs text-muted">{typeLabel}</span>
                    <span className="text-xs text-muted">·</span>
                    <LemonBadge size="small" status={STATUS_COLORS[status] ?? 'muted'} content={status} />
                    {survey.questions.length > 0 && (
                        <>
                            <span className="text-xs text-muted">·</span>
                            <span className="text-xs text-muted">
                                {survey.questions.length} {survey.questions.length === 1 ? 'question' : 'questions'}
                            </span>
                        </>
                    )}
                </div>
            </div>
            {canPreview && (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconEye />}
                    onClick={() => previewLiveSurvey(survey.id)}
                    tooltip="Preview on this page"
                    className="shrink-0"
                />
            )}
        </div>
    )
}
