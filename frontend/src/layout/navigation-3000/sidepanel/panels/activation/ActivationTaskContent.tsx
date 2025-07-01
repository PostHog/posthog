import React from 'react'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { ActivationTask } from './activationLogic'

export const IngestFirstEventContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Install PostHog in your app and send your first event to unlock all analytics features. Choose from our{' '}
            <Link to="https://posthog.com/docs/libraries">JavaScript, Python, Node.js, React, or mobile SDKs</Link>.
        </p>
        <p>
            Get started in minutes with our{' '}
            <Link to="https://posthog.com/docs/getting-started/install">installation guide</Link> or{' '}
            <Link to="https://posthog.com/docs/getting-started/send-events">learn how to send custom events</Link>.
        </p>
    </div>
)

export const InviteTeamMemberContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Invite teammates to collaborate on insights, dashboards, and feature flags. Multiple team members can share
            different perspectives and catch issues you might miss.
        </p>
        <p>
            You can manage permissions and roles in{' '}
            <Link to={urls.settings('organization-members')}>
                <strong>organization settings</strong>
            </Link>{' '}
            after sending invites.
        </p>
    </div>
)

export const SetUpReverseProxyContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            A reverse proxy enables you to send events to PostHog Cloud using your own domain. Using a reverse proxy
            means that events are less likely to be intercepted by tracking blockers.
        </p>
        <p>
            Choose from our{' '}
            <Link to="https://posthog.com/docs/advanced/proxy/managed-reverse-proxy">managed reverse proxy</Link> or set
            up your own with <Link to="https://posthog.com/docs/advanced/proxy/cloudflare">Cloudflare</Link>,{' '}
            <Link to="https://posthog.com/docs/advanced/proxy/nginx">nginx</Link>, or{' '}
            <Link to="https://posthog.com/docs/advanced/proxy">other proxy options</Link>.
        </p>
    </div>
)

export const activationTaskContentMap: Partial<Record<ActivationTask, React.FC>> = {
    [ActivationTask.IngestFirstEvent]: IngestFirstEventContent,
    [ActivationTask.InviteTeamMember]: InviteTeamMemberContent,
    [ActivationTask.SetUpReverseProxy]: SetUpReverseProxyContent,
}
