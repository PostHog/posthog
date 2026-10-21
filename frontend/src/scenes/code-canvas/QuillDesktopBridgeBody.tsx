import { IconLaptop } from '@posthog/icons'
import { Button, Heading, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { desktopBridgeDescription, openInDesktop } from './desktopBridge'
import type { DesktopBridgeBodyProps } from './DesktopBridgeBody'

/** The quill view of `DesktopBridgeBody`, for visitors on the `today-rail-nav` redesign. */
export function QuillDesktopBridgeBody({ subject, deepLink, webUrl }: DesktopBridgeBodyProps): JSX.Element {
    return (
        <div data-quill className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
            <IconLaptop className="text-5xl shrink-0" />
            <div className="flex flex-col gap-2">
                <Heading size="xl" render={<h2 className="m-0" />}>
                    Opening in PostHog Desktop…
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {desktopBridgeDescription(subject, !!webUrl)}
                </Text>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
                {deepLink && (
                    <Button elevated variant="primary" size="lg" onClick={() => openInDesktop(deepLink)}>
                        Open in desktop app
                    </Button>
                )}
                {webUrl && (
                    <Button
                        elevated
                        variant="outline"
                        size="lg"
                        render={<LinkPrimitive to={webUrl} />}
                        data-attr="desktop-bridge-open-in-browser"
                    >
                        Open in browser
                    </Button>
                )}
            </div>
            <Button variant="link" render={<LinkPrimitive to="https://posthog.com/desktop" target="_blank" />}>
                Download PostHog Desktop
            </Button>
        </div>
    )
}
