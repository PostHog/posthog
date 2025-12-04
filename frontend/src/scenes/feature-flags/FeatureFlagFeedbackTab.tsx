import { BindLogic, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonTable, LemonTableColumn, Link, Spinner } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { QuickSurveyForm } from 'scenes/surveys/QuickSurveyModal'
import { SurveyResult } from 'scenes/surveys/SurveyView'
import { SurveyStatusTag } from 'scenes/surveys/components/SurveyStatusTag'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveysTabs, surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { FeatureFlagType, Survey } from '~/types'

export function FeedbackTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const { surveysResponsesCountLoading, surveysResponsesCount } = useValues(surveysLogic)
    const surveysForFlag = featureFlag.surveys || []

    if (surveysForFlag.length === 0) {
        return (
            <div className="flex flex-col items-center pt-5">
                <div className="w-full max-w-5xl">
                    <LemonBanner type="info" className="mb-6">
                        Gather valuable insights by automatically displaying a survey to users in this feature flag
                    </LemonBanner>
                    <div className="border rounded p-6 bg-bg-light">
                        <QuickSurveyForm
                            context={{
                                type: QuickSurveyType.FEATURE_FLAG,
                                flag: featureFlag,
                            }}
                        />
                    </div>
                </div>
            </div>
        )
    }

    if (surveysForFlag.length === 1) {
        return (
            <BindLogic logic={surveyLogic} props={{ id: surveysForFlag[0].id }}>
                <div className="">
                    <LemonBanner type="info" className="mb-6">
                        Showing results for survey "{surveysForFlag[0].name}".{' '}
                        <Link to={urls.survey(surveysForFlag[0].id)}>
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
            <LemonBanner type="info" className="">
                Showing only surveys associated with this feature flag.{' '}
                <Link to={urls.surveys(SurveysTabs.Active)}>
                    See all surveys <IconArrowRight />
                </Link>
            </LemonBanner>

            <LemonTable
                dataSource={surveysForFlag}
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
