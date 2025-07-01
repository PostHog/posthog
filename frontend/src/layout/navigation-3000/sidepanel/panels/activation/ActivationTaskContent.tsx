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
            We offer a{' '}
            <Link to="https://posthog.com/docs/advanced/proxy/managed-reverse-proxy">
                managed reverse proxy service
            </Link>{' '}
            that simplifies deployment and management, or you can set up your own with{' '}
            <Link to="https://posthog.com/docs/advanced/proxy/cloudflare">Cloudflare</Link>,{' '}
            <Link to="https://posthog.com/docs/advanced/proxy/nginx">nginx</Link>, or{' '}
            <Link to="https://posthog.com/docs/advanced/proxy">other proxy options</Link>.
        </p>
    </div>
)

export const CreateFirstInsightContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Create your first insight to analyze user behavior patterns in your product. Insights let you visualize
            events, actions, and user properties to understand how people use your app.
        </p>
        <p>
            Start with a <Link to="https://posthog.com/docs/product-analytics/trends/overview">trends insight</Link> to
            track events over time, or explore{' '}
            <Link to="https://posthog.com/docs/product-analytics/insights">other insight types</Link> like retention,
            funnels, and user paths.
        </p>
    </div>
)

export const CreateFirstDashboardContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Create a dashboard to organize your insights and get an overview view of your product metrics. Dashboards
            help you track key performance indicators and share data with your team.
        </p>
        <p>
            Choose from <Link to="https://posthog.com/templates">ready-made templates</Link> for common use cases or
            start with a <Link to="https://posthog.com/docs/product-analytics/dashboards">blank dashboard</Link> to
            customize your own metrics view.
        </p>
    </div>
)

export const TrackCustomEventsContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Set up custom events to track specific user actions that matter most to your product. While autocapture
            handles basic interactions, custom events give you precise control over what data you collect.
        </p>
        <p>
            Follow our{' '}
            <Link to="https://posthog.com/tutorials/event-tracking-guide">complete event tracking guide</Link> to
            implement custom events using the{' '}
            <Link to="https://posthog.com/docs/getting-started/send-events">capture method</Link> in your codebase.
        </p>
    </div>
)

export const activationTaskContentMap: Partial<Record<ActivationTask, React.FC>> = {
    [ActivationTask.IngestFirstEvent]: IngestFirstEventContent,
    [ActivationTask.InviteTeamMember]: InviteTeamMemberContent,
    [ActivationTask.SetUpReverseProxy]: SetUpReverseProxyContent,
    [ActivationTask.CreateFirstInsight]: CreateFirstInsightContent,
    [ActivationTask.CreateFirstDashboard]: CreateFirstDashboardContent,
    [ActivationTask.TrackCustomEvents]: TrackCustomEventsContent,
}
