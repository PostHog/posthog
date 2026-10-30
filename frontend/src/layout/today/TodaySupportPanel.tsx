import { useActions, useValues } from 'kea'

import { IconExternal, IconFeatures, IconHelmet, IconMap } from '@posthog/icons'
import { Button, Heading, Skeleton, Text, cn } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingPlan, SidePanelTab } from '~/types'

import { QuillSupportTickets } from 'products/conversations/frontend/components/QuillSidePanel/QuillSupportTickets'
import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'

import { todayContextPanelLogic } from './todayContextPanelLogic'
import { TodaySupportResponseTimes } from './TodaySupportResponseTimes'
import { TodaySupportStatusAlert } from './TodaySupportStatusAlert'

// Set through the `support-message-override` feature flag, for times like an offsite or the holidays.
const SUPPORT_MESSAGE_OVERRIDE_TITLE = "We're catching up on our support queue"
const SUPPORT_MESSAGE_OVERRIDE_BODY =
    'Our support engineers recently attended an offsite to make long-term enhancements to our support process. As a result, our response times are slightly delayed for some inquiries. Thanks for your patience as we work to get caught up!'

const FEEDBACK_LINKS = [
    { label: "See what we're building", href: 'https://posthog.com/wip', Icon: IconHelmet },
    { label: 'Vote on our roadmap', href: 'https://posthog.com/roadmap', Icon: IconMap },
    { label: 'Request a feature', href: 'https://posthog.com/roadmap?idea=new', Icon: IconFeatures },
]

function ExternalLinkButton({ href, children }: { href: string; children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-elements
        <Button variant="outline" render={<a href={href} target="_blank" rel="noopener noreferrer" />}>
            {children}
        </Button>
    )
}

export function TodaySupportPanel(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { billing, billingLoading, billingPlan } = useValues(billingLogic)
    const { tickets, canCreateTicket, view } = useValues(sidepanelTicketsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { togglePanelTab } = useActions(todayContextPanelLogic)

    const isCloudOrDev = preflight?.cloud || process.env.NODE_ENV === 'development'
    const billingLoaded = !billingLoading && billing !== undefined
    // Free plans can't open new tickets, but tickets they already have stay readable and repliable.
    const showTickets = isCloudOrDev && (canCreateTicket || tickets.length > 0)

    // An open ticket, a new ticket or recovery fills the panel on its own, so the thread and composer get the room.
    // An open ticket scrolls its own thread. The forms scroll as a whole, so Submit stays reachable in a short panel.
    if (showTickets && view !== 'list') {
        return (
            <div className={cn('flex min-h-0 flex-1 flex-col p-3', view !== 'ticket' && 'overflow-y-auto')}>
                <QuillSupportTickets />
            </div>
        )
    }

    return (
        <div className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4">
            <div className="mx-auto flex w-full max-w-160 flex-col gap-6 p-4">
                {!billingLoaded ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-5 w-1/3" />
                        <Skeleton className="h-16" />
                    </div>
                ) : (
                    <>
                        {isCloudOrDev && (
                            <section className="flex flex-col gap-2">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    Ask PostHog AI
                                </Heading>
                                <Text size="xs" variant="muted">
                                    PostHog AI can answer most of the support questions we receive. It reads our docs
                                    for you, and writes SQL queries, expressions and regex patterns.
                                </Text>
                                <Button
                                    variant="primary"
                                    onClick={() => togglePanelTab(SidePanelTab.Max)}
                                    data-attr="support-panel-chat-with-ai"
                                >
                                    Chat with PostHog AI
                                </Button>
                            </section>
                        )}

                        {showTickets ? (
                            <section className="flex flex-col gap-2">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    {canCreateTicket ? 'Contact us' : 'Your tickets'}
                                </Heading>
                                <TodaySupportStatusAlert />
                                {featureFlags[FEATURE_FLAGS.SUPPORT_MESSAGE_OVERRIDE] && (
                                    <div className="flex flex-col gap-1 rounded-md border border-border p-3">
                                        <Text size="xs" weight="semibold">
                                            {SUPPORT_MESSAGE_OVERRIDE_TITLE}
                                        </Text>
                                        <Text size="xs" variant="muted">
                                            {SUPPORT_MESSAGE_OVERRIDE_BODY}
                                        </Text>
                                    </div>
                                )}
                                <Text size="xs" variant="muted">
                                    {canCreateTicket
                                        ? "Can't find what you need, and PostHog AI couldn't help? Message our support engineers."
                                        : 'You can keep replying to tickets you already have open.'}
                                </Text>
                                <QuillSupportTickets />
                            </section>
                        ) : (
                            <section className="flex flex-col gap-2">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    Can't find what you need in the docs?
                                </Heading>
                                <Text size="xs" variant="muted">
                                    With the free plan you can ask the community, or explore your upgrade choices to
                                    message our support engineers.
                                </Text>
                            </section>
                        )}
                    </>
                )}

                <section className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Ask the community
                    </Heading>
                    <Text size="xs" variant="muted">
                        Questions about features, how-tos, or use cases? There are thousands of discussions in our
                        community forums.
                    </Text>
                    <ExternalLinkButton href="https://posthog.com/questions">
                        Ask the community
                        <IconExternal />
                    </ExternalLinkButton>
                </section>

                <section className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Support is open Monday to Friday
                    </Heading>
                    <TodaySupportResponseTimes />
                    {billingPlan !== BillingPlan.Enterprise && (
                        <Button
                            variant="link"
                            size="sm"
                            className="self-end p-0"
                            render={<LinkPrimitive to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])} />}
                        >
                            Upgrade support plan
                        </Button>
                    )}
                </section>

                <section className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Share feedback
                    </Heading>
                    <div className="flex flex-col items-start gap-2">
                        {FEEDBACK_LINKS.map(({ label, href, Icon }) => (
                            <ExternalLinkButton key={href} href={href}>
                                <Icon />
                                {label}
                            </ExternalLinkButton>
                        ))}
                    </div>
                </section>
            </div>
        </div>
    )
}
