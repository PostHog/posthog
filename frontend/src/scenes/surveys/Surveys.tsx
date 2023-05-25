import { LemonButton, LemonTable, LemonDivider, Link, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { getSurveyStatus, surveysLogic } from './surveysLogic'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Survey } from '~/types'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { useValues } from 'kea'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
}

// function getResponsesCount(survey: Survey): number {
//     return 0
// }

export function Surveys(): JSX.Element {
    const { surveys } = useValues(surveysLogic)

    return (
        <div className="mt-10">
            <PageHeader
                title="Surveys"
                buttons={
                    <LemonButton type="primary" to={urls.survey('new')} data-attr="new-survey">
                        New survey
                    </LemonButton>
                }
            />
            <LemonTable
                className="mt-6"
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                        render: function RenderName(_, survey) {
                            return (
                                <>
                                    <Link to={urls.survey(survey.id)} className="row-name">
                                        {stringWithWBR(survey.name, 17)}
                                    </Link>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Responses',
                        render: function RenderResponses() {
                            // const responsesCount = getResponsesCount(survey)
                            return <div>{0}</div>
                        },
                    },
                    {
                        dataIndex: 'type',
                        title: 'Type',
                    },
                    createdByColumn<Survey>() as LemonTableColumn<Survey, keyof Survey | undefined>,
                    createdAtColumn<Survey>() as LemonTableColumn<Survey, keyof Survey | undefined>,
                    {
                        title: 'Status',
                        width: 100,
                        render: function Render(_, survey: Survey) {
                            const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
                            const status = getSurveyStatus(survey)
                            return (
                                <LemonTag color={statusColors[status]} style={{ fontWeight: 600 }}>
                                    {status.toUpperCase()}
                                </LemonTag>
                            )
                        },
                    },
                    {
                        width: 0,
                        render: function Render() {
                            return (
                                <More
                                    overlay={
                                        <>
                                            <LemonButton status="stealth" fullWidth>
                                                View results
                                            </LemonButton>
                                            <LemonButton status="stealth" fullWidth onClick={() => {}}>
                                                Edit
                                            </LemonButton>
                                            <LemonDivider />
                                            <LemonButton status="danger" onClick={() => {}} fullWidth>
                                                Delete
                                            </LemonButton>
                                        </>
                                    }
                                />
                            )
                        },
                    },
                ]}
                dataSource={surveys}
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                nouns={['survey', 'surveys']}
            />
        </div>
    )
}
