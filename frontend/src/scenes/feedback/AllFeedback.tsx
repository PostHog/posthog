import { LemonButton, LemonDivider, LemonSwitch, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { feedbackLogic } from './feedbackLogic'

import './Feedback.scss'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { InAppFeedback, InAppFeedbackHeaderButtons } from './InAppFeedback'
import { UserInterviewScheduler, UserInterviewSchedulerHeaderButtons } from './UserInterviewScheduler'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { urls } from 'scenes/urls'

export const Feedback = (): JSX.Element => {
    // const { activeTab } = useValues(feedbackLogic)
    // const { setActiveTab } = useActions(feedbackLogic)

    // return (
    //     <div className="Feedback">
    //         <PageHeader
    //             title={
    //                 <div className="flex items-center gap-2">
    //                     Feedback
    //                     <LemonTag type="warning" className="uppercase">
    //                         Alpha
    //                     </LemonTag>
    //                 </div>
    //             }
    //             buttons={
    //                 activeTab === 'in-app-feedback' ? (
    //                     <InAppFeedbackHeaderButtons />
    //                 ) : (
    //                     <UserInterviewSchedulerHeaderButtons />
    //                 )
    //             }
    //         />
    //         <LemonTabs
    //             activeKey={activeTab}
    //             onChange={(key) => {
    //                 setActiveTab(key)
    //             }}
    //             tabs={[
    //                 {
    //                     content: <InAppFeedback />,
    //                     key: 'in-app-feedback',
    //                     label: 'In-app feedback',
    //                 },
    //                 {
    //                     content: <UserInterviewScheduler />,
    //                     key: 'user-interview-scheduler',
    //                     label: 'User interview scheduler',
    //                 },
    //             ]}
    //         />
    //     </div>
    // )
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
                                    <Link
                                        to={urls.feedback(feedback.id)
                                            // feedback.id ? urls.featureFlag(featureFlag.id) : undefined
                                        }
                                        className="row-name"
                                    >
                                        {stringWithWBR(feedback.name, 17)}
                                    </Link>
                                </>
                            )
                        }
                    },
                    {
                        dataIndex: 'responses',
                        title: 'Responses'
                    },
                    {
                        dataIndex: 'type',
                        title: 'Type'
                    },
                    {
                        dataIndex: 'created_by',
                        // sorter: function noRefCheck() { },
                        title: 'Created by',
                        // tooltip: 'What they are primarily working on.'
                    },
                    {
                        dataIndex: 'created_at',
                        title: 'Created at',
                    },
                    {
                        title: 'Status',
                        dataIndex: 'active',
                        // sorter: (a: FeatureFlagType, b: FeatureFlagType) => Number(a.active) - Number(b.active),
                        width: 100,
                        render: function RenderActive(_, feedback) {
                            return (
                                <>
                                    <LemonSwitch checked={feedback.active} onChange={() => { }} />
                                    {/* {feedback.active ? (<LemonTag type="success" className="uppercase">
                                        Enabled
                                    </LemonTag>
                                    ) : (
                                        <LemonTag type="default" className="uppercase">
                                            Disabled
                                        </LemonTag>
                                    )} */}
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
                                            <LemonButton status="stealth" fullWidth>View results</LemonButton>
                                            {/* {feedback?.id && ( */}
                                            <LemonButton
                                                status="stealth"
                                                fullWidth
                                                onClick={() => { }
                                                    // featureFlag.id && router.actions.push(urls.featureFlag(featureFlag.id))
                                                }
                                            >
                                                Edit
                                            </LemonButton>
                                            {/* )} */}
                                            <LemonDivider />
                                            {/* {featureFlag.id && ( */}
                                            <LemonButton
                                                status="danger"
                                                onClick={() => {
                                                    // deleteWithUndo({
                                                    //     endpoint: `projects/${currentTeamId}/feature_flags`,
                                                    //     object: { name: featureFlag.key, id: featureFlag.id },
                                                    //     callback: loadFeatureFlags,
                                                    // })
                                                }}
                                                // disabled={!featureFlag.can_edit}
                                                fullWidth
                                            >
                                                Delete {feedback.type.toLowerCase()}
                                            </LemonButton>
                                            {/* )} */}
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
                    }
                ]}
                onRow={function noRefCheck() { }}
                onSort={function noRefCheck() { }}
            />

        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
