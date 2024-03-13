import { LemonCard, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'

import { InviteMembersButton } from '~/layout/navigation/TopBar/AccountPopover'

import { OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

const proxyDocs = [
    {
        title: 'AWS CloudFront',
        link: 'https://posthog.com/docs/advanced/proxy/cloudfront',
    },
    {
        title: 'Caddy',
        link: 'https://posthog.com/docs/advanced/proxy/caddy',
    },
    {
        title: 'Cloudflare',
        link: 'https://posthog.com/docs/advanced/proxy/cloudflare',
    },
    {
        title: 'Kubernetes Ingress Controller',
        link: 'https://posthog.com/docs/advanced/proxy/kubernetes-ingress-controller',
    },
    {
        title: 'Netlify',
        link: 'https://posthog.com/docs/advanced/proxy/netlify',
    },
    {
        title: 'Next.js rewrites',
        link: 'https://posthog.com/docs/advanced/proxy/nextjs',
    },
    {
        title: 'Next.js middleware',
        link: 'https://posthog.com/docs/advanced/proxy/nextjs-middleware',
    },
    {
        title: 'Vercel',
        link: 'https://posthog.com/docs/advanced/proxy/vercel',
    },
    {
        title: 'Nuxt',
        link: 'https://posthog.com/docs/advanced/proxy/nuxt',
    },
]

export const OnboardingReverseProxy = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { preflight } = useValues(preflightLogic)
    const { inviteTeamMembers } = useActions(inviteLogic)
    const { invitesToSend, canSubmit: canSubmitInvites } = useValues(inviteLogic)

    return (
        <OnboardingStep
            title="Reverse proxy (optional)"
            stepKey={stepKey}
            continueText="I've already done this"
            showSkip
            continueAction={() =>
                preflight?.email_service_available &&
                invitesToSend[0]?.target_email &&
                canSubmitInvites &&
                inviteTeamMembers()
            }
        >
            <div className="mb-6 mt-6">
                <p>A reverse proxy allows you to send events to PostHog Cloud using your own domain.</p>
                <p>
                    This means that events are sent from your own domain and are less likely to be intercepted by
                    tracking blockers. You'll be able to capture more usage data without having to self-host PostHog.
                </p>
                <p>
                    Setting up a reverse proxy means setting up a service to redirect requests from a subdomain you
                    choose (like <span className="font-mono break-keep">e.yourdomain.com</span>) to PostHog. It is best
                    practice to use a subdomain that does not include posthog, analytics, tracking, or other similar
                    words.
                </p>
                <h3>Documentation</h3>
                <p>Here are some popular reverse proxy options:</p>
                <ul className="list-disc list-inside ml-2">
                    {proxyDocs.map(({ title, link }) => (
                        <li key={title}>
                            <Link to={link} target="_blank">
                                {title}
                            </Link>
                        </li>
                    ))}
                </ul>
                <LemonCard className="mt-6" hoverEffect={false}>
                    <div className="sm:flex sm:items-start sm:justify-between">
                        <div>
                            <h3 className="font-bold">Need help with this step?</h3>
                            <p className="mb-0">Invite a team member to help you get set up.</p>
                        </div>
                        <div className="max-w-44 mt-4 sm:mt-0">
                            <InviteMembersButton type="secondary" />
                        </div>
                    </div>
                </LemonCard>
            </div>
        </OnboardingStep>
    )
}
