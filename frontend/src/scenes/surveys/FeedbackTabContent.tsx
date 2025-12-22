import { BindLogic, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonTable, LemonTableColumn, Link, Spinner } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SurveyResult } from 'scenes/surveys/SurveyView'
import { SurveyStatusTag } from 'scenes/surveys/components/SurveyStatusTag'
import { QuickSurveyContext } from 'scenes/surveys/quick-create/types'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { Survey } from '~/types'

import { QuickSurveyForm } from './QuickSurveyModal'

export interface FeedbackTabContentProps {
    surveys: Survey[]
    context: QuickSurveyContext
    emptyStateBannerMessage: string
    multipleSurveysBannerMessage: React.ReactNode
}

export function FeedbackTabContent({
    surveys,
    context,
    emptyStateBannerMessage,
    multipleSurveysBannerMessage,
}: FeedbackTabContentProps): JSX.Element {
    const { surveysResponsesCountLoading, surveysResponsesCount } = useValues(surveysLogic)

    if (surveys.length === 0) {
        return (
            <div className="flex flex-col items-center pt-5">
                <div className="w-full max-w-5xl">
                    <LemonBanner type="info" className="mb-6">
                        {emptyStateBannerMessage}
                    </LemonBanner>
                    <div className="border rounded p-6 bg-bg-light">
                        <QuickSurveyForm context={context} />
                    </div>
                </div>
            </div>
        )
    }

    if (surveys.length === 1) {
        const survey = surveys[0]
        return (
            <BindLogic logic={surveyLogic} props={{ id: survey.id }}>
                <div>
                    <LemonBanner type="info" className="mb-6">
                        Showing results for survey "{survey.name}".{' '}
                        <Link to={urls.survey(survey.id)}>
                            Manage in surveys <IconArrowRight />
                        </Link>
                    </LemonBanner>
                    <SurveyResult />
                </div>
            </BindLogic>
        )
    }

    return (
        <div className="space-y-6">
            <LemonBanner type="info">{multipleSurveysBannerMessage}</LemonBanner>

            <LemonTable
                dataSource={surveys}
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                rowKey="name"
                nouns={['survey', 'surveys']}
                data-attr="surveys-table"
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                        render: function RenderName(_, survey) {
                            return <LemonTableLink to={urls.survey(survey.id)} title={stringWithWBR(survey.name, 17)} />
                        },
                    },
                    {
                        title: 'Responses',
                        dataIndex: 'id',
                        render: function RenderResponses(_, survey) {
                            return (
                                <>
                                    {surveysResponsesCountLoading ? (
                                        <Spinner />
                                    ) : (
                                        <div>{surveysResponsesCount[survey.id] ?? 0}</div>
                                    )}
                                </>
                            )
                        },
                        sorter: (surveyA, surveyB) => {
                            const countA = surveysResponsesCount[surveyA.id] ?? 0
                            const countB = surveysResponsesCount[surveyB.id] ?? 0
                            return countA - countB
                        },
                    },
                    createdAtColumn<Survey>() as LemonTableColumn<Survey, keyof Survey | undefined>,
                    {
                        title: 'Status',
                        width: 100,
                        render: function Render(_: any, survey: Survey) {
                            return <SurveyStatusTag survey={survey} />
                        },
                    },
                ]}
            />
        </div>
    )
}
