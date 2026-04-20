import { useActions, useValues } from 'kea'

import { LemonBadge, LemonSkeleton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { joinWithUiHost } from '~/toolbar/utils'
import { Survey, SurveyType } from '~/types'

import { getSurveyStatus, surveysToolbarLogic } from './surveysToolbarLogic'

const SURVEY_TYPE_LABELS: Record<SurveyType, string> = {
    [SurveyType.Popover]: 'Popover',
    [SurveyType.Widget]: 'Widget',
    [SurveyType.FullScreen]: 'Full screen',
    [SurveyType.API]: 'API',
    [SurveyType.ExternalSurvey]: 'External',
}

const STATUS_COLORS: Record<string, 'primary' | 'muted' | 'danger'> = {
    active: 'primary',
    draft: 'muted',
    complete: 'muted',
}

function SurveyRow({ survey }: { survey: Survey }): JSX.Element {
    const { uiHost } = useValues(toolbarConfigLogic)
    const status = getSurveyStatus(survey)
    const typeLabel = SURVEY_TYPE_LABELS[survey.type] ?? survey.type

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
        </div>
    )
}

export function SurveysToolbarMenu(): JSX.Element {
    const { searchTerm, allSurveys, allSurveysLoading } = useValues(surveysToolbarLogic)
    const { setSearchTerm, loadSurveys } = useActions(surveysToolbarLogic)

    useOnMountEffect(() => {
        loadSurveys()
    })

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput
                    autoFocus
                    placeholder="Search surveys"
                    fullWidth
                    type="search"
                    value={searchTerm}
                    onChange={(s) => setSearchTerm(s)}
                />
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="mt-1">
                    {allSurveysLoading ? (
                        <div className="space-y-3 py-1">
                            {Array.from({ length: 3 }).map((_, i) => (
                                <div key={i} className="space-y-1.5 py-1">
                                    <LemonSkeleton className="h-4 w-3/4" />
                                    <LemonSkeleton className="h-3 w-1/2" />
                                </div>
                            ))}
                        </div>
                    ) : allSurveys.length > 0 ? (
                        allSurveys.map((survey: Survey) => <SurveyRow key={survey.id} survey={survey} />)
                    ) : (
                        <div className="text-muted text-sm text-center py-4">
                            {searchTerm ? 'No matching surveys found.' : 'No surveys found in this project.'}
                        </div>
                    )}
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
