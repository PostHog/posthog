import useSize from '@react-hook/size'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonTag, lemonToast } from '@posthog/lemon-ui'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { getApprovalActionLabel, getApprovalResourceName, getApprovalResourceUrl } from 'scenes/approvals/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ApprovalDecision, ChangeRequest, ChangeRequestState } from '~/types'

import { ChangeRequestActions } from './ChangeRequestActions'
import { ApprovalLogicProps, ProposedChangesTab, approvalLogic } from './approvalLogic'
import { generateDecisionAnalysis } from './decisionAnalysis'

export const scene: SceneExport<ApprovalLogicProps> = {
    component: ApprovalDetail,
    logic: approvalLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function ApprovalDetail({ id }: ApprovalLogicProps): JSX.Element {
    const { changeRequest, changeRequestLoading, changeRequestMissing, proposedChangesTab } = useValues(
        approvalLogic({ id })
    )
    const { approveChangeRequest, rejectChangeRequest, cancelChangeRequest, setProposedChangesTab } = useActions(
        approvalLogic({ id })
    )

    const containerRef = useRef<HTMLDivElement>(null)
    const [width] = useSize(containerRef)

    if (changeRequestMissing) {
        return <NotFound object="change request" />
    }

    if (changeRequestLoading || !changeRequest) {
        return (
            <SceneContent>
                <LemonSkeleton />
            </SceneContent>
        )
    }

    const decisionAnalysis = generateDecisionAnalysis(changeRequest)

    return (
        <SceneContent>
            <SceneTitleSection
                name={getApprovalActionLabel(changeRequest.action_key)}
                description={changeRequest.intent_display?.description}
                resourceType={{ type: 'change_request' }}
                actions={
                    <ChangeRequestActions
                        changeRequest={changeRequest}
                        onApprove={() => approveChangeRequest()}
                        onReject={(_, reason) => {
                            if (reason) {
                                rejectChangeRequest(reason)
                            } else {
                                lemonToast.error('Please provide a reason for rejection')
                            }
                        }}
                        onCancel={(_, reason) => cancelChangeRequest(reason)}
                        showViewButton={false}
                    />
                }
            />
            <SceneDivider />

            <div className="space-y-6">
                <section>
                    <h3 className="font-semibold mb-2">Details</h3>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <div className="text-secondary text-sm">Status</div>
                            <div className="mt-1">
                                <StatusTag state={changeRequest.state} />
                            </div>
                        </div>
                        <div>
                            <div className="text-secondary text-sm">Requested by</div>
                            <div className="mt-1 flex items-center gap-2">
                                <ProfilePicture name={changeRequest.created_by.first_name} size="md" />
                                <div>
                                    <div>{changeRequest.created_by.first_name}</div>
                                    <div className="text-xs text-secondary">{changeRequest.created_by.email}</div>
                                </div>
                            </div>
                        </div>
                        <div>
                            <div className="text-secondary text-sm">Resource</div>
                            <div className="mt-1">
                                {(() => {
                                    const resourceUrl = getApprovalResourceUrl(
                                        changeRequest.action_key,
                                        changeRequest.resource_id
                                    )
                                    const name = getApprovalResourceName(
                                        changeRequest.resource_type,
                                        changeRequest.intent
                                    )
                                    return resourceUrl && name ? <Link to={resourceUrl}>{name}</Link> : name
                                })()}
                            </div>
                        </div>
                        <div>
                            <div className="text-secondary text-sm">Approvals</div>
                            <div className="mt-1">
                                {changeRequest.approvals?.length || 0} / {changeRequest.policy_snapshot?.quorum || 1}
                            </div>
                        </div>
                        <div>
                            <div className="text-secondary text-sm">Created</div>
                            <div className="mt-1">{dayjs(changeRequest.created_at).format('MMMM D, YYYY h:mm A')}</div>
                        </div>
                        <div>
                            <div className="text-secondary text-sm">Expires</div>
                            <div className="mt-1">
                                {changeRequest.state === ChangeRequestState.Pending ? (
                                    <>
                                        {dayjs(changeRequest.expires_at).format('MMMM D, YYYY h:mm A')}
                                        <span className="text-secondary ml-1">
                                            ({dayjs(changeRequest.expires_at).fromNow()})
                                        </span>
                                    </>
                                ) : (
                                    'N/A'
                                )}
                            </div>
                        </div>
                    </div>
                </section>

                <LemonDivider />

                <section>
                    <h3 className="font-semibold mb-2">Proposed changes</h3>
                    <ProposedChangesTabs
                        changeRequest={changeRequest}
                        containerRef={containerRef}
                        width={width}
                        activeTab={proposedChangesTab}
                        setActiveTab={setProposedChangesTab}
                    />
                </section>

                <LemonDivider />

                <section>
                    <h3 className="font-semibold mb-2">Decision Analysis</h3>
                    <div className="bg-bg-light p-4 rounded border">
                        <div className="text-base font-medium mb-2">{decisionAnalysis.summary}</div>
                        <div className="text-sm text-secondary whitespace-pre-line">{decisionAnalysis.details}</div>
                    </div>
                </section>

                {changeRequest.approvals && changeRequest.approvals.length > 0 && (
                    <>
                        <LemonDivider />
                        <section>
                            <h3 className="font-semibold mb-2">Approval Timeline</h3>
                            <div className="space-y-3">
                                {changeRequest.approvals.map((approval) => (
                                    <div key={approval.id} className="flex items-start gap-3">
                                        <div className="flex-shrink-0 mt-1">
                                            <LemonTag
                                                type={
                                                    approval.decision === ApprovalDecision.Approved
                                                        ? 'success'
                                                        : 'danger'
                                                }
                                            >
                                                {approval.decision}
                                            </LemonTag>
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2">
                                                <ProfilePicture name={approval.created_by.first_name} size="md" />
                                                <div>
                                                    <div>{approval.created_by.first_name}</div>
                                                    <span className="text-secondary text-sm">
                                                        {dayjs(approval.created_at).fromNow()}
                                                    </span>
                                                </div>
                                            </div>
                                            {approval.reason && (
                                                <div className="text-sm text-secondary mt-1">{approval.reason}</div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>
                    </>
                )}

                {changeRequest.state === ChangeRequestState.Applied && changeRequest.result_data && (
                    <>
                        <LemonDivider />
                        <section>
                            <h3 className="font-semibold mb-2">Application Result</h3>
                            <div className="bg-bg-light p-4 rounded border">
                                <pre className="text-sm overflow-x-auto">
                                    {JSON.stringify(changeRequest.result_data, null, 2)}
                                </pre>
                            </div>
                        </section>
                    </>
                )}

                {changeRequest.state === ChangeRequestState.Failed && changeRequest.apply_error && (
                    <>
                        <LemonDivider />
                        <section>
                            <h3 className="font-semibold mb-2">Error</h3>
                            <div className="bg-bg-light p-4 rounded border">
                                <div className="text-danger text-sm">{changeRequest.apply_error}</div>
                            </div>
                        </section>
                    </>
                )}

                {changeRequest.validation_errors && (
                    <>
                        <LemonDivider />
                        <section>
                            <h3 className="font-semibold mb-2">Validation Errors</h3>
                            <div className="bg-warning-light p-4 rounded border border-warning">
                                <pre className="text-sm overflow-x-auto">
                                    {JSON.stringify(changeRequest.validation_errors, null, 2)}
                                </pre>
                            </div>
                        </section>
                    </>
                )}

                <LemonDivider />

                <section>
                    <h3 className="font-semibold mb-2">Policy Configuration</h3>
                    <div className="bg-bg-light p-4 rounded border">
                        <pre className="text-sm overflow-x-auto">
                            {JSON.stringify(changeRequest.policy_snapshot, null, 2)}
                        </pre>
                    </div>
                </section>
            </div>
        </SceneContent>
    )
}

function ProposedChangesTabs({
    changeRequest,
    containerRef,
    width,
    activeTab,
    setActiveTab,
}: {
    changeRequest: ChangeRequest
    containerRef: React.RefObject<HTMLDivElement>
    width: number | null
    activeTab: ProposedChangesTab
    setActiveTab: (tab: ProposedChangesTab) => void
}): JSX.Element {
    const hasGatedChanges = changeRequest.intent_display?.before && changeRequest.intent_display?.after
    const fullRequestData = changeRequest.intent?.full_request_data

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={(key) => setActiveTab(key as ProposedChangesTab)}
            tabs={[
                {
                    key: 'gated',
                    label: 'Gated changes',
                    content: hasGatedChanges ? (
                        <div ref={containerRef} className="flex flex-col space-y-2 w-full">
                            <MonacoDiffEditor
                                original={JSON.stringify(changeRequest.intent_display.before, null, 2)}
                                modified={JSON.stringify(changeRequest.intent_display.after, null, 2)}
                                language="json"
                                width={width || '100%'}
                                options={{
                                    renderOverviewRuler: false,
                                    scrollBeyondLastLine: false,
                                    hideUnchangedRegions: {
                                        enabled: true,
                                        contextLineCount: 3,
                                        minimumLineCount: 3,
                                        revealLineCount: 20,
                                    },
                                    diffAlgorithm: 'advanced',
                                }}
                            />
                        </div>
                    ) : (
                        <div className="bg-bg-light p-4 rounded border">
                            <pre className="text-sm overflow-x-auto">
                                {JSON.stringify(changeRequest.intent_display, null, 2)}
                            </pre>
                        </div>
                    ),
                },
                {
                    key: 'full',
                    label: 'Full request payload',
                    content: (
                        <div className="bg-bg-light p-4 rounded border">
                            <p className="text-sm text-secondary mb-2">
                                This is the complete request payload that will be applied when the change is approved.
                            </p>
                            <pre className="text-sm overflow-x-auto">
                                {JSON.stringify(fullRequestData || changeRequest.intent, null, 2)}
                            </pre>
                        </div>
                    ),
                },
            ]}
        />
    )
}

function StatusTag({ state }: { state: ChangeRequestState }): JSX.Element {
    const tagTypes = {
        [ChangeRequestState.Pending]: 'default',
        [ChangeRequestState.Approved]: 'primary',
        [ChangeRequestState.Applied]: 'success',
        [ChangeRequestState.Rejected]: 'danger',
        [ChangeRequestState.Expired]: 'warning',
        [ChangeRequestState.Failed]: 'danger',
    } as const

    return (
        <LemonTag type={tagTypes[state]} className="uppercase">
            {state}
        </LemonTag>
    )
}
