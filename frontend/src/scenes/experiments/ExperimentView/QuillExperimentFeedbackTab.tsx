import { BindLogic, useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import { IconArrowRight, IconInfo, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Spinner,
    Text,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { QuillTimeCell } from 'lib/components/QuillTableCells/QuillTableCells'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { QuickSurveyForm } from 'scenes/surveys/QuickSurveyModal'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveysTabs, getSurveyStatus, surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { Experiment, ProgressStatus, Survey } from '~/types'

import { SurveyResult } from 'products/surveys/frontend/SurveyResult'

import {
    FEEDBACK_DRAFT_NOTE,
    FEEDBACK_EMPTY_DESCRIPTION,
    FEEDBACK_EMPTY_HEADER,
    FEEDBACK_LOAD_ERROR,
} from './ExperimentFeedbackTab'
import { experimentFeedbackTabLogic } from './experimentFeedbackTabLogic'
import { QuillSectionHeading } from './QuillCardParts'

const SURVEY_STATUS_BADGE: Record<ProgressStatus, { label: string; variant: 'success' | 'default' | 'completed' }> = {
    running: { label: 'Running', variant: 'success' },
    draft: { label: 'Draft', variant: 'default' },
    complete: { label: 'Complete', variant: 'completed' },
}

type SortingState = NonNullable<DataTableProps<Survey, unknown>['sorting']>

function InfoNote({ children, dataAttr }: { children: ReactNode; dataAttr?: string }): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone="info" data-attr={dataAttr}>
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemDescription className="line-clamp-none">{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

function InlineLink({ to, children }: { to: string; children: ReactNode }): JSX.Element {
    return (
        <Button variant="link" size="inline" nativeButton={false} render={<LinkPrimitive to={to} />}>
            {children}
            <IconArrowRight />
        </Button>
    )
}

function QuillSurveysTable({ surveys }: { surveys: Survey[] }): JSX.Element {
    const { surveysResponsesCountLoading, surveysResponsesCount } = useValues(surveysLogic)
    const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }])

    const columns: DataTableProps<Survey, unknown>['columns'] = [
        {
            id: 'name',
            header: 'Name',
            meta: { expand: true },
            accessorFn: (survey) => survey.name,
            cell: ({ row: { original } }) => (
                <div className="min-w-0">
                    <Button
                        variant="link-foreground"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.survey(original.id)} />}
                    >
                        {original.name}
                    </Button>
                </div>
            ),
        },
        {
            id: 'responses',
            header: 'Responses',
            meta: { align: 'right' },
            accessorFn: (survey) => surveysResponsesCount[survey.id] ?? 0,
            cell: ({ row: { original } }) =>
                surveysResponsesCountLoading ? <Spinner /> : (surveysResponsesCount[original.id] ?? 0),
        },
        {
            id: 'created_at',
            header: 'Created',
            accessorFn: (survey) => survey.created_at,
            cell: ({ row: { original } }) => <QuillTimeCell time={original.created_at} />,
        },
        {
            id: 'status',
            header: 'Status',
            accessorFn: (survey) => getSurveyStatus(survey),
            cell: ({ row: { original } }) => {
                const status = SURVEY_STATUS_BADGE[getSurveyStatus(original)]
                return (
                    <Badge variant={status.variant} data-attr="status">
                        {status.label}
                    </Badge>
                )
            },
        },
    ]

    return (
        <Card size="sm" flush className="pt-0" data-attr="surveys-table">
            <DataTable
                columns={columns}
                data={surveys}
                fullWidth
                size="sm"
                getRowId={(survey) => survey.id}
                sorting={sorting}
                onSortingChange={setSorting}
            />
        </Card>
    )
}

function QuillFeedbackContent({ experiment, surveys }: { experiment: Experiment; surveys: Survey[] }): JSX.Element {
    if (surveys.length === 0) {
        return (
            <div className="flex flex-col items-center pt-5">
                <div className="flex w-full max-w-5xl flex-col gap-2">
                    <QuillSectionHeading>{FEEDBACK_EMPTY_HEADER}</QuillSectionHeading>
                    <Text size="sm" variant="muted" render={<p className="mb-4 max-w-prose" />}>
                        {FEEDBACK_EMPTY_DESCRIPTION}
                    </Text>
                    <Card className="p-6">
                        <QuickSurveyForm context={{ type: QuickSurveyType.EXPERIMENT, experiment }} />
                    </Card>
                </div>
            </div>
        )
    }

    if (surveys.length === 1) {
        const survey = surveys[0]
        return (
            <BindLogic logic={surveyLogic} props={{ id: survey.id }}>
                <div className="flex flex-col gap-6">
                    <InfoNote>
                        Showing results for survey "{survey.name}".{' '}
                        <InlineLink to={urls.survey(survey.id)}>Manage in surveys</InlineLink>
                    </InfoNote>
                    <SurveyResult />
                </div>
            </BindLogic>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            <InfoNote>
                Showing only surveys associated with this experiment.{' '}
                <InlineLink to={urls.surveys(SurveysTabs.Active)}>See all surveys</InlineLink>
            </InfoNote>
            <QuillSurveysTable surveys={surveys} />
        </div>
    )
}

export function QuillExperimentFeedbackTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentFeedbackTabLogic({ experiment })
    const { experimentSurveys, experimentSurveysLoaded, experimentSurveysLoading, experimentSurveysLoadFailed } =
        useValues(logic)
    const { loadExperimentSurveys } = useActions(logic)

    if (!experimentSurveysLoaded || experimentSurveysLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Spinner />
            </div>
        )
    }

    if (experimentSurveysLoadFailed) {
        return (
            <Item variant="outline" size="sm" tone="destructive">
                <ItemMedia variant="icon" aria-hidden>
                    <IconWarning />
                </ItemMedia>
                <ItemContent>
                    <ItemDescription className="line-clamp-none">{FEEDBACK_LOAD_ERROR}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={loadExperimentSurveys}>
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            {/* A reset experiment is a draft whose flag stays active, so its surveys keep showing */}
            {!experiment.start_date && !experiment.feature_flag?.active && (
                <InfoNote dataAttr="experiment-feedback-draft-note">{FEEDBACK_DRAFT_NOTE}</InfoNote>
            )}
            <QuillFeedbackContent experiment={experiment} surveys={experimentSurveys} />
        </div>
    )
}
