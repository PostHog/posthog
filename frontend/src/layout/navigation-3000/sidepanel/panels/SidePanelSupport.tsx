import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ProductKey, SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { title } = useValues(theLogic)
    const { closeSupportForm } = useActions(theLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const hasPrioritySupport = hasAvailableFeature(AvailableFeature.PRIORITY_SUPPORT)

    return (
        <>
            <SidePanelPaneHeader title={title} />

            <div className="overflow-y-auto" data-attr="side-panel-support-container">
                <div className="p-3 max-w-160 w-full mx-auto">
                    {hasAvailableFeature(AvailableFeature.EMAIL_SUPPORT) ? (
                        <>
                            <SupportForm />
                            <footer>
                                <LemonButton
                                    form="support-modal-form"
                                    htmlType="submit"
                                    type="primary"
                                    data-attr="submit"
                                    fullWidth
                                    center
                                    className="mt-4"
                                >
                                    Submit
                                </LemonButton>
                                <LemonButton
                                    form="support-modal-form"
                                    type="secondary"
                                    onClick={closeSupportForm}
                                    fullWidth
                                    center
                                    className="mt-2"
                                >
                                    Cancel
                                </LemonButton>
                                <div className="border border-border p-4 rounded mt-6">
                                    <p>
                                        <code className="text-xs">
                                            Your support priority:{' '}
                                            <LemonTag type={hasPrioritySupport ? 'success' : 'primary'}>
                                                {hasPrioritySupport ? 'High' : 'Normal'}
                                            </LemonTag>
                                        </code>
                                    </p>
                                    {hasPrioritySupport ? (
                                        <>
                                            <h3>Your tickets come first</h3>
                                            <p>
                                                Thanks for being a priority customer. Your tickets will be prioritized,
                                                and you can expect to hear back from us soon.
                                            </p>
                                        </>
                                    ) : (
                                        <>
                                            <h3>Upgrade your plan to get priority support</h3>
                                            <p>
                                                Upgrade your Platform & Support plan to Teams or Enterprise to get
                                                priority support from our team.
                                            </p>
                                            <div className="flex">
                                                <LemonButton
                                                    type="primary"
                                                    to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                                                >
                                                    Upgrade now
                                                </LemonButton>
                                            </div>
                                        </>
                                    )}
                                </div>
                            </footer>
                        </>
                    ) : (
                        <div className="flex flex-col gap-y-8">
                            <div>
                                <h3>Search our docs and knowledgebase</h3>
                                <p>
                                    Most questions about using PostHog are answered in our docs. We also have guides
                                    galore for different frameworks, integrations, and more.
                                </p>
                                <div className="flex">
                                    <LemonButton type="primary" to="https://posthog.com/docs">
                                        Search the docs
                                    </LemonButton>
                                </div>
                                <p className="text-xs italic mt-2 mb-0">Ps. You can ask questions there, too!</p>
                            </div>
                            <div>
                                <h3>Ask the community</h3>
                                <p>
                                    If you can't find it in our docs, ask a question in our community forum, where
                                    community members and the PostHog team can help you with questions.
                                </p>
                                <div className="flex">
                                    <LemonButton type="primary" to="https://posthog.com/questions">
                                        Ask the community
                                    </LemonButton>
                                </div>
                            </div>
                            <div>
                                <h3>Report a bug</h3>
                                <p>
                                    If you've found a bug, open an issue in GitHub and the correct team will prioritize
                                    and take a look.
                                </p>
                                <div className="flex">
                                    <LemonButton
                                        type="primary"
                                        to="https://github.com/PostHog/posthog/issues/new?template=bug_report.md"
                                    >
                                        Report a bug
                                    </LemonButton>
                                </div>
                            </div>
                            <div>
                                <h3>Request a feature</h3>
                                <p>
                                    If you'd like to request a new feature for PostHog, please do so in GitHub! Do us a
                                    favor and search around to make sure it hasn't been submitted already before
                                    submitting a new one 😊
                                </p>
                                <div className="flex">
                                    <LemonButton
                                        type="primary"
                                        to="https://github.com/PostHog/posthog/issues/new?template=feature_request.md"
                                    >
                                        Request a feature
                                    </LemonButton>
                                </div>
                            </div>
                            <div className="border border-border p-4 rounded">
                                <p>
                                    <code className="text-xs">
                                        Your support priority: <LemonTag type="danger">Free / none</LemonTag>
                                    </code>
                                </p>
                                <h3>Upgrade to a paid plan for email support</h3>
                                <p>
                                    Upgrade to a paid plan for any product to get access to our support team and
                                    engineers via email.
                                </p>
                                <div className="flex">
                                    <LemonButton type="primary" to={urls.organizationBilling()}>
                                        Upgrade now
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </>
    )
}
