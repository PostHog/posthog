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
        <p>Invite teammates to collaborate with you in PostHog.</p>
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
            Choose from ready-made templates for common use cases or start with a blank dashboard to customize your own
            metrics view.
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

export const SetupSessionRecordingsContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Enable session recordings to see exactly how users navigate through your product. Session replay captures
            user interactions, clicks, and page views so you can identify pain points and optimize user experience.
        </p>
        <p>
            Follow the <Link to="https://posthog.com/docs/session-replay/installation">installation guide</Link> to
            enable recordings.
        </p>
    </div>
)

export const WatchSessionRecordingContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>Watch your first session recording to understand how real users interact with your product.</p>
        <p>
            Visit the <Link to={urls.replay()}>replay page</Link> to browse available recordings, or learn{' '}
            <Link to="https://posthog.com/docs/session-replay/how-to-watch-recordings">
                how to watch recordings effectively
            </Link>{' '}
            to get the most insights from user sessions.
        </p>
    </div>
)

export const LaunchExperimentContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Launch your first A/B test to validate feature changes and product decisions with real user data.
            Experiments help you understand which variants perform better before rolling them out to all users.
        </p>
        <p>
            Start by creating an experiment on the experiment page, then follow our guide on{' '}
            <Link to="https://posthog.com/docs/experiments/installation">installing the SDK</Link> and{' '}
            <Link to="https://posthog.com/docs/experiments/adding-experiment-code">adding experiment code</Link> to your
            product.
        </p>
    </div>
)

export const ConnectSourceContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Connect external data sources to combine your product analytics with business data from your CRM, payment
            processor, or database. This gives you a complete view of user behavior and business outcomes.
        </p>
        <p>
            Learn how to <Link to="https://posthog.com/docs/cdp/sources">link a source</Link> to explore data from
            sources like Stripe and your database.
        </p>
    </div>
)

export const LaunchSurveyContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Create targeted surveys to collect direct feedback from users about their experience and needs. Surveys help
            you understand the "why" behind user behavior patterns. Get started by{' '}
            <Link to="https://posthog.com/docs/surveys/installation">installing the SDK</Link>.
        </p>
    </div>
)

export const CollectSurveyResponsesContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Analyze survey responses to gain insights into user satisfaction, feature requests, and pain points. Survey
            data complements your behavioral analytics with direct user feedback.
        </p>
        <p>
            Visit the <Link to={urls.surveys()}>surveys page</Link> to review responses and learn{' '}
            <Link to="https://posthog.com/docs/surveys/viewing-results">how to analyze survey results</Link>.
        </p>
    </div>
)

export const CreateFeatureFlagContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Create your first feature flag to safely release new features and control which users see them. Feature
            flags let you test changes with specific user groups before rolling them out to everyone.
        </p>
        <p>
            Learn{' '}
            <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags">how to create a feature flag</Link>{' '}
            and{' '}
            <Link to="https://posthog.com/docs/feature-flags/adding-feature-flag-code">
                add the code to your product
            </Link>{' '}
            to start controlling feature releases.
        </p>
    </div>
)

export const UpdateFeatureFlagReleaseConditionsContent = (): JSX.Element => (
    <div className="text-sm text-muted space-y-2">
        <p>
            Update your feature flag release conditions to control who sees your feature. You can target specific users,
            roll out to a percentage of traffic, or use custom properties to define your audience.
        </p>
        <p>
            Visit the <Link to={urls.featureFlags()}>Feature flags page</Link> to modify release conditions and learn{' '}
            <Link to="https://posthog.com/docs/feature-flags/testing">how to test your feature flags</Link> before going
            live.
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
    [ActivationTask.SetupSessionRecordings]: SetupSessionRecordingsContent,
    [ActivationTask.WatchSessionRecording]: WatchSessionRecordingContent,
    [ActivationTask.CreateFeatureFlag]: CreateFeatureFlagContent,
    [ActivationTask.UpdateFeatureFlagReleaseConditions]: UpdateFeatureFlagReleaseConditionsContent,
    [ActivationTask.LaunchExperiment]: LaunchExperimentContent,
    [ActivationTask.ConnectSource]: ConnectSourceContent,
    [ActivationTask.LaunchSurvey]: LaunchSurveyContent,
    [ActivationTask.CollectSurveyResponses]: CollectSurveyResponsesContent,
}
