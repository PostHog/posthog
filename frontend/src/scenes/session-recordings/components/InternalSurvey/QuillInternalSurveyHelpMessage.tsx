import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

function DocsLink({ to, children }: { to: string; children: string }): JSX.Element {
    return (
        <Button variant="link" size="inline" nativeButton={false} render={<LinkPrimitive to={to} target="_blank" />}>
            {children}
        </Button>
    )
}

function HelpList({ items }: { items: (string | JSX.Element)[] }): JSX.Element {
    return (
        <ul className="m-0 flex list-disc flex-col gap-1 pl-4">
            {items.map((item, index) => (
                <Text key={index} size="xs" render={<li />}>
                    {item}
                </Text>
            ))}
        </ul>
    )
}

export function QuillInternalSurveyHelpMessage({ title }: { title: string }): JSX.Element | null {
    if (title === 'Cannot configure to my needs') {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    There are several ways to control which sessions you record:
                </Text>
                <HelpList
                    items={[
                        <DocsLink
                            key="programmatic"
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#programmatically-start-and-stop-recordings"
                        >
                            Programmatically start and stop recordings
                        </DocsLink>,
                        <DocsLink
                            key="url"
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-url-trigger-conditions"
                        >
                            With URL trigger conditions
                        </DocsLink>,
                        <DocsLink
                            key="event"
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-event-trigger-conditions"
                        >
                            With Event trigger conditions
                        </DocsLink>,
                        <DocsLink
                            key="flags"
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-feature-flags"
                        >
                            With feature flags
                        </DocsLink>,
                        <DocsLink
                            key="sampling"
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#sampling"
                        >
                            Sampling
                        </DocsLink>,
                    ]}
                />
            </div>
        )
    }

    if (title === 'Privacy/Legal concerns') {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    PostHog offers a range of controls to limit what data is captured by session recordings. Our privacy
                    controls run in the browser or mobile app. So, masked data is never sent over the network to
                    PostHog.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    <DocsLink to="https://posthog.com/docs/session-replay/privacy">Learn more</DocsLink>
                </Text>
            </div>
        )
    }

    if (title === 'Too expensive') {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    There are several ways to reduce costs by recording fewer sessions:
                </Text>
                <HelpList
                    items={[
                        'Disable automatic recording and programmatically start and stop recordings',
                        'Set a feature flag with the conditions that define which users or sessions you want to record.',
                        'Set a minimum recording duration.',
                        'Set a sampling rate for recordings.',
                        'Start recording only after certain events (for example after an error).',
                        'Start recording only after visiting certain pages (for example to avoid starting for every visit to the home page).',
                    ]}
                />
                <Text size="xs" render={<p className="m-0" />}>
                    <DocsLink to="https://posthog.com/docs/session-replay/cutting-costs">Learn more</DocsLink>
                </Text>
            </div>
        )
    }

    if (title === 'Performance issues') {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Session replay allows you to capture network requests and responses, providing insights into network
                    performance and potential issues. This feature can be particularly useful for debugging and
                    optimizing your application's network interactions.
                </Text>
                <HelpList
                    items={[
                        <DocsLink
                            key="network"
                            to="https://posthog.com/docs/session-replay/network-performance-recording"
                        >
                            Network performance recording
                        </DocsLink>,
                        <DocsLink
                            key="canvas"
                            to="https://posthog.com/docs/session-replay/canvas-recording#canvas-recording-performance"
                        >
                            Canvas recording performance
                        </DocsLink>,
                        <DocsLink
                            key="angular"
                            to="https://posthog.com/docs/session-replay/troubleshooting#angular-performance"
                        >
                            Angular performance
                        </DocsLink>,
                    ]}
                />
            </div>
        )
    }

    return null
}
