import { LemonSelect } from "@posthog/lemon-ui"
import { Radio } from "antd"
import { useValues } from "kea"
import { EditableField } from "lib/components/EditableField/EditableField"
import { ObjectTags } from "lib/components/ObjectTags/ObjectTags"
import { PageHeader } from "lib/components/PageHeader"
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

            />
                <span>Select a feedback type</span>
                <div>
                    <Radio>
                        <h4>Feature survey</h4>
                        <div>Connect a feature to a survey and evaluate its qualitative success.</div>
                    </Radio>
                </div>
                
            </div>
    )
}

export function FeedbackSummary(): JSX.Element {
    return (
        <div>summary</div>
    )
}