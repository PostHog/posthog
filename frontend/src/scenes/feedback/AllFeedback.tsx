import { LemonButton, LemonDivider, LemonSwitch, LemonTable, Link } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { feedbackLogic } from './feedbackLogic'

import './Feedback.scss'
import { More } from 'lib/lemon-ui/LemonButton/More'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { urls } from 'scenes/urls'

export const Feedback = (): JSX.Element => {
    return (
        <div className="mt-10">
            <PageHeader
                title="Feedback"
                buttons={
                    <LemonButton type="primary" to={urls.feedback('new')} data-attr="new-feedback">
                        New feedback
                    </LemonButton>
                }
            />
            <LemonTable
                className="mt-6"
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                        render: function RenderName(_, feedback) {
                            return (
                                <>
                                    <Link to={urls.feedback(feedback.id)} className="row-name">
                                        {stringWithWBR(feedback.name, 17)}
                                    </Link>
                                </>
                            )
                        },
                    },
                    {
                        dataIndex: 'responses',
                        title: 'Responses',
                    },
                    {
                        dataIndex: 'type',
                        title: 'Type',
                    },
                    {
                        dataIndex: 'created_by',
                        title: 'Created by',
                    },
                    {
                        dataIndex: 'created_at',
                        title: 'Created at',
                    },
                    {
                        title: 'Status',
                        dataIndex: 'active',
                        width: 100,
                        render: function RenderActive(_, feedback) {
                            return (
                                <>
                                    <LemonSwitch checked={feedback.active} onChange={() => {}} />
                                </>
                            )
                        },
                    },
                    {
                        width: 0,
                        render: function Render(_, feedback) {
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
                                                Delete {feedback.type.toLowerCase()}
                                            </LemonButton>
                                        </>
                                    }
                                />
                            )
                        },
                    },
                ]}
                dataSource={[
                    {
                        id: 1,
                        name: 'Early access beta feature survey',
                        responses: 33,
                        type: 'Feature survey',
                        created_by: 'Eric',
                        created_at: 'Today',
                        active: true,
                    },
                    {
                        id: 2,
                        name: 'PostHog 3000 beta survey',
                        responses: 85,
                        type: 'Feature survey',
                        created_by: 'Michael',
                        created_at: 'Yesterday',
                        active: false,
                    },
                    {
                        id: 3,
                        name: 'General app feedback',
                        responses: 130,
                        type: 'Feedback',
                        created_by: 'Annika',
                        created_at: '10 days ago',
                        active: true,
                    },
                ]}
                onRow={function noRefCheck() {}}
                onSort={function noRefCheck() {}}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
