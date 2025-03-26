import { IconFeatures, IconHelmet, IconMap } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { getPublicSupportSnippet, supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature, BillingPlanType, ProductKey, SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { sidePanelStatusLogic } from './sidePanelStatusLogic'

const Section = ({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement => {
    return (
        <section className="mb-6">
            <>
                <h3>{title}</h3>
                {children}
            </>
        </section>
    )
}

// In order to set these turn on the `support-message-override` feature flag.
const SUPPORT_MESSAGE_OVERRIDE_TITLE = '🎄 🎅 Support during the holidays 🎁 ⛄'
const SUPPORT_MESSAGE_OVERRIDE_BODY =
    "We're offering reduced support while we celebrate the holidays. Responses may be slower than normal over the holiday period (23rd December to the 6th January), and between the 25th and 27th of December we'll only be responding to critical issues. Thanks for your patience!"

const SupportFormBlock = ({ onCancel }: { onCancel: () => void }): JSX.Element => {
    const { supportPlans, hasSupportAddonPlan } = useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Section title="Email an engineer">
            <SupportForm />
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
                onClick={onCancel}
                fullWidth
                center
                className="mt-2 mb-4"
            >
                Cancel
            </LemonButton>
            <br />
            {featureFlags[FEATURE_FLAGS.SUPPORT_MESSAGE_OVERRIDE] ? (
                <div className="border bg-surface-primary p-2 rounded gap-2">
                    <strong>{SUPPORT_MESSAGE_OVERRIDE_TITLE}</strong>
                    <p className="mt-2 mb-0">{SUPPORT_MESSAGE_OVERRIDE_BODY}</p>
                </div>
            ) : (
                <div className="grid grid-cols-2 border rounded [&_>*]:px-2 [&_>*]:py-0.5 mb-4 bg-surface-primary pt-4">
                    <div className="col-span-full flex justify-between py-1">
                        {/* If placing a support message, replace the line below with explanation */}
                        <strong>Avg support response times</strong>
                        <div>
                            <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                                Explore options
                            </Link>
                        </div>
                    </div>
                    {/* If placing a support message, comment out (don't remove) the section below */}
                    {supportPlans?.map((plan: BillingPlanType) => {
                        // If they have an addon plan, only show the addon plan
                        const currentPlan =
                            plan.current_plan && (!hasSupportAddonPlan || plan.plan_key?.includes('addon'))
                        return (
                            <React.Fragment key={`support-panel-${plan.plan_key}`}>
                                <div className={currentPlan ? 'font-bold' : undefined}>
                                    {plan.name}
                                    {currentPlan && (
                                        <>
                                            {' '}
                                            <span className="font-normal opacity-60 text-sm">(your plan)</span>
                                        </>
                                    )}
                                </div>
                                <div className={currentPlan ? 'font-bold' : undefined}>
                                    {plan.features.find((f) => f.key == AvailableFeature.SUPPORT_RESPONSE_TIME)?.note}
                                </div>
                            </React.Fragment>
                        )
                    })}
                </div>
            )}
        </Section>
    )
}

export const SidePanelSupport = (): JSX.Element => {
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { status } = useValues(sidePanelStatusLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { openEmailForm, closeEmailForm } = useActions(theLogic)
    const { isEmailFormOpen } = useValues(theLogic)

    const region = preflight?.region

    return (
        <>
            <div className="overflow-y-auto flex flex-col h-full" data-attr="side-panel-support-container">
                <SidePanelPaneHeader title="Help" />
                <div className="p-3 max-w-160 w-full mx-auto flex-1 flex flex-col justify-center">
                    {isEmailFormOpen ? (
                        <SupportFormBlock onCancel={() => closeEmailForm()} />
                    ) : (
                        <>
                            {status !== 'operational' ? (
                                <Section title="">
                                    <LemonBanner type={status.includes('outage') ? 'error' : 'warning'}>
                                        <div>
                                            <span>
                                                We are experiencing {status.includes('outage') ? 'major' : ''} issues.
                                            </span>
                                            <LemonButton
                                                type="secondary"
                                                fullWidth
                                                center
                                                targetBlank
                                                onClick={() => openSidePanel(SidePanelTab.Status)}
                                                className="mt-2 bg-[white]"
                                            >
                                                View system status
                                            </LemonButton>
                                        </div>
                                    </LemonBanner>
                                </Section>
                            ) : null}

                            {isCloudOrDev ? (
                                <Section title="Ask Max AI">
                                    <div>
                                        <p>Max AI can now answer 80%+ of the support questions we receive! Nice.</p>
                                        <p>
                                            Let Max read 100s of pages of docs for you, write SQL queries and
                                            expressions, regex patterns, etc.
                                        </p>
                                        <LemonButton
                                            type="primary"
                                            fullWidth
                                            center
                                            onClick={() => {
                                                openSidePanel(
                                                    SidePanelTab.Docs,
                                                    '/docs/new-to-posthog/understand-posthog?chat=open'
                                                )
                                            }}
                                            targetBlank={false}
                                            className="mt-2"
                                        >
                                            Chat with Max AI
                                        </LemonButton>
                                    </div>
                                </Section>
                            ) : null}

                            {isCloudOrDev ? (
                                <Section title="Contact us">
                                    <p>Can't find what you need and Max unable to help?</p>
                                    <LemonButton
                                        type="secondary"
                                        fullWidth
                                        center
                                        onClick={() => openEmailForm()}
                                        targetBlank
                                        className="mt-2"
                                    >
                                        Email our support engineers
                                    </LemonButton>
                                </Section>
                            ) : null}

                            <Section title="Ask the community">
                                <p>
                                    Questions about features, how-tos, or use cases? There are thousands of discussions
                                    in our community forums.
                                </p>
                                <LemonButton
                                    type="secondary"
                                    fullWidth
                                    center
                                    to="https://posthog.com/questions"
                                    targetBlank
                                    className="mt-2"
                                >
                                    Ask the community
                                </LemonButton>
                            </Section>

                            <Section title="Share feedback">
                                <ul>
                                    <li>
                                        <LemonButton
                                            type="secondary"
                                            status="alt"
                                            to="https://posthog.com/wip"
                                            icon={<IconHelmet />}
                                            targetBlank
                                        >
                                            See what we're building
                                        </LemonButton>
                                    </li>
                                    <li>
                                        <LemonButton
                                            type="secondary"
                                            status="alt"
                                            to="https://posthog.com/roadmap"
                                            icon={<IconMap />}
                                            targetBlank
                                        >
                                            Vote on our roadmap
                                        </LemonButton>
                                    </li>
                                    <li>
                                        <LemonButton
                                            type="secondary"
                                            status="alt"
                                            to={`https://github.com/PostHog/posthog/issues/new?&labels=enhancement&template=feature_request.yml&debug-info=${encodeURIComponent(
                                                getPublicSupportSnippet(region, currentOrganization, currentTeam)
                                            )}`}
                                            icon={<IconFeatures />}
                                            targetBlank
                                        >
                                            Request a feature
                                        </LemonButton>
                                    </li>
                                </ul>
                            </Section>
                        </>
                    )}
                </div>
            </div>
        </>
    )
}
