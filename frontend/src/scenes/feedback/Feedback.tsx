import { LemonButton, LemonCollapse, LemonDivider, LemonInput, LemonTable, LemonTextArea, Link } from "@posthog/lemon-ui"
import { useValues } from "kea"
import { EditableField } from "lib/components/EditableField/EditableField"
import { ObjectTags } from "lib/components/ObjectTags/ObjectTags"
import { PageHeader } from "lib/components/PageHeader"
import { IconPlus } from "lib/lemon-ui/icons"
import { LemonMenu } from "lib/lemon-ui/LemonMenu/LemonMenu"
import { LemonTabs } from "lib/lemon-ui/LemonTabs"
import { useState } from "react"
import { FlagSelector } from "scenes/early-access-features/EarlyAccessFeature"
import { SceneExport } from "scenes/sceneTypes"
import { tagsModel } from "~/models/tagsModel"

export const scene: SceneExport = {
    component: Feedback,
    // logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }): (any)['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

export function Feedback({ id }: { id?: string } = {}): JSX.Element {
    const isNewFeedback = id === 'new' || id === undefined

    return (
        <div>
            {isNewFeedback ?
                <FeedbackForm /> :
                <FeedbackSummary />}
        </div>

    )
}

export function FeedbackForm(): JSX.Element {
    const feedback = { name: 'New feedback', description: null, tags: [] }
    const feedbackLoading = false
    const canEditFeedback = true
    const { tags } = useValues(tagsModel)

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center">
                        <EditableField
                            name="name"
                            value={feedback?.name || (feedbackLoading ? 'Loading…' : '')}
                            placeholder="Name this feedback"
                            onSave={
                                // dashboard
                                //     ? (value) => updateDashboard({ id: feedback.id, name: value, allowUndo: true })
                                //     : 
                                undefined
                            }
                            saveOnBlur={true}
                            minLength={1}
                            maxLength={400} // Sync with Dashboard model
                            // mode={!canEditDashboard ? 'view' : undefined}
                            // notice={
                            //     dashboard && !canEditDashboard
                            //         ? {
                            //             icon: <IconLock />,
                            //             tooltip: DASHBOARD_CANNOT_EDIT_MESSAGE,
                            //         }
                            //         : undefined
                            // }
                            data-attr="feedback-name"
                        />
                    </div>
                }
                caption={
                    <>
                        {feedback && !!(canEditFeedback || feedback.description) && (
                            <EditableField
                                multiline
                                name="description"
                                value={feedback.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) => { }
                                    // updateDashboard({ id: dashboard.id, description: value, allowUndo: true })
                                }
                                saveOnBlur={true}
                                compactButtons
                            // mode={!canEditDashboard ? 'view' : undefined}
                            // paywall={!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)}
                            />
                        )}
                        {feedback?.tags && (
                            <>
                                {canEditFeedback ? (
                                    <ObjectTags
                                        tags={feedback.tags}
                                        // onChange={(_, tags) => triggerDashboardUpdate({ tags })}
                                        saving={feedbackLoading}
                                        tagsAvailable={tags.filter((tag) => !feedback.tags?.includes(tag))}
                                        className="insight-metadata-tags"
                                    />
                                ) : feedback.tags.length ? (
                                    <ObjectTags
                                        tags={feedback.tags}
                                        saving={feedbackLoading}
                                        staticOnly
                                        className="insight-metadata-tags"
                                    />
                                ) : null}
                            </>
                        )}
                    </>
                }
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-feedback"
                            type="secondary"
                            onClick={() => {
                                // if (isEditingFlag) {
                                //     editFeatureFlag(false)
                                //     loadFeatureFlag()
                                // } else {
                                //     router.actions.push(urls.featureFlags())
                                // }
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-feedback"
                            htmlType="submit"
                            loading={feedbackLoading}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            />
            <LemonDivider />
            <div className="flex flex-row h-full">
                <div className="flex-col">
                    <div className="my-4">
                        <h3>Display conditions</h3>
                        <div>
                            <h4>Link to feature (optional)</h4>
                            <div className="text-muted">Connect to a feature flag to track qualitative feature success.</div>
                            <div className="mb-2">
                                <FlagSelector value={'5'} onChange={() => { }} />
                            </div>

                            <div className="text-muted">Choose where your feedback prompt will show either on a url or based on a CSS selector.</div>
                            <span>Url</span>
                            <LemonInput />

                            <span>Selector</span>
                            <LemonInput />
                        </div>
                    </div>
                    <div>
                        <LemonDivider className="my-2" />
                        <h3>Questions</h3>
                        <LemonCollapse className="w-180 border rounded p-2"
                            panels={[
                                {
                                    content:
                                        <>
                                            <div className="mb-2">
                                                <span>Title</span>
                                                <LemonInput />
                                            </div>
                                            <div className="mb-2">
                                                <span>Description (optional)</span>
                                                <LemonTextArea />
                                            </div>
                                        </>,
                                    header: 'New feedback question',
                                    key: '1',
                                }
                            ]}
                        />

                        <LemonMenu
                            sameWidth
                            placement="bottom"
                            items={[{ label: 'Open text' }, { label: 'Emoji rating' }, { label: 'NPS' }]}
                        >
                            <LemonButton type="primary" className="my-3" icon={<IconPlus />}>
                                New question
                            </LemonButton>

                        </LemonMenu>
                    </div>

                </div>
                <div className="ml-4 pl-2 w-full flex justify-center flex-col" style={{ borderLeft: '2px solid' }}>
                    <div className="text-center">Preview</div>
                    <div className="border rounded p-4 mt-6">
                        <h2>Do you have any feedback for this feature?</h2>
                        <span>optional description text</span>
                        <LemonTextArea className="mt-2" />
                        <LemonButton className="mt-4" type="primary">Finish</LemonButton>
                    </div>
                </div>
            </div>

        </div>
    )
}

export function FeedbackSummary(): JSX.Element {
    const [tabKey, setTabKey] = useState("results")
    return (
        <div>
            <PageHeader
                title={'Early access beta feature survey'}
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton type="secondary" status="danger">Stop</LemonButton>
                    </div>
                }
            />
            <LemonTabs activeKey={tabKey} onChange={(key) => setTabKey(key)} tabs={[
                {
                    content: <div>
                        <div>
                            <h3>Connected feature</h3>
                            <Link>early-access-features</Link>
                        </div>

                        <div>
                            <h3>Display conditions</h3>
                            <span>Url: app.posthog.com/early-access-features</span>
                        </div>
                        <div className="my-4">
                            <h3>Questions</h3>
                            <span>Do you have any feedback for early access features?</span>
                        </div>
                        </div>,
                    key: 'overview',
                    label: 'Overview'
                },
                {
                    content: <div>
                        <div className="flex flex-row gap-4">
                            <div className="border rounded p-4">
                                <span>Impressions</span>
                                <h2>257</h2>
                            </div>
                            <div className="border rounded p-4">
                                <span>Started</span>
                                <h2>78</h2>
                            </div>
                            <div className="border rounded p-4">
                                <span>Completed</span>
                                <h2>55</h2>
                            </div>
                        </div>
                        <LemonDivider />
                        <LemonButton type="secondary" className="mb-2">filter buttons and such</LemonButton>
                        <LemonTable
                            columns={[{ dataIndex: 'response', title: 'Response', width: 600 }, { dataIndex: 'email', title: 'Email' }]}
                            dataSource={[
                                { response: 'This feature has changed my life!! Before this feature I wasnt able to test my releases and now I can. Thanks so much posthog team!', email: 'iloveposthog@email.com' },
                                { response: "I don't really understand how to use this feature, are there any tutorials or docs on it?", email: 'kendall@email.com' },
                                { response: "my sesion recording is broken, help????", email: 'communityengineer12@email.com' },
                                { response: "survey response", email: '' },
                                { response: "survey response", email: '' },
                                { response: "survey response", email: '' }
                            ]}
                        /></div>,
                    key: 'results',
                    label: 'Results'
                }
            ]}
            />
        </div>
    )
}