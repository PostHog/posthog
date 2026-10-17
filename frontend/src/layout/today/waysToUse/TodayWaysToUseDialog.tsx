import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconMCP } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Highlight,
} from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { McpIllustration } from './illustrations/McpIllustration'
import { SlackIllustration } from './illustrations/SlackIllustration'
import { WebAppIllustration } from './illustrations/WebAppIllustration'
import { waysToUseLogic } from './waysToUseLogic'
import { WaysToUseSurfaceCard } from './WaysToUseSurfaceCard'
import { WaysToUseSurfaceLink } from './WaysToUseSurfaceLink'

export function TodayWaysToUseDialog(): JSX.Element {
    const { isOpen } = useValues(waysToUseLogic)
    const { closeWaysToUse } = useActions(waysToUseLogic)
    const popupRef = useRef<HTMLDivElement>(null)

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && closeWaysToUse('dismiss')}>
            <DialogContent
                ref={popupRef}
                size="wide"
                initialFocus={popupRef}
                className="group/popup lg:max-w-4xl"
                data-attr="today-ways-to-use-dialog"
            >
                <DialogHeader className="items-center text-center">
                    <DialogTitle className="text-lg">
                        PostHog,{' '}
                        <Highlight animate delay={300}>
                            wherever you work
                        </Highlight>
                    </DialogTitle>
                    <DialogDescription className="max-w-xl text-balance">
                        Bring your product data into the tools you already use.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="@container">
                        <div className="grid grid-cols-1 gap-x-4 gap-y-8 @3xl:grid-cols-3">
                            <WaysToUseSurfaceCard
                                logo={<Logomark size="xs" />}
                                title="In the web app"
                                description="See what changed today, ask PostHog AI, and open any product."
                                illustration={<WebAppIllustration />}
                                action={
                                    <WaysToUseSurfaceLink surface="chat" to={urls.taskNewSession()}>
                                        Start a chat
                                    </WaysToUseSurfaceLink>
                                }
                            />
                            <WaysToUseSurfaceCard
                                logo={<IconSlack className="size-5" />}
                                title="In Slack"
                                description="Mention @PostHog with a data question, quick fix, or chore."
                                illustration={<SlackIllustration />}
                                action={
                                    <WaysToUseSurfaceLink
                                        surface="slack"
                                        to={urls.settings('environment-integrations')}
                                    >
                                        Connect Slack
                                    </WaysToUseSurfaceLink>
                                }
                            />
                            <WaysToUseSurfaceCard
                                logo={<IconMCP className="size-5" />}
                                title="In your coding agent"
                                description="Plug PostHog into Claude, Cursor, and anything else that speaks MCP."
                                illustration={<McpIllustration />}
                                action={
                                    <WaysToUseSurfaceLink surface="mcp" to={urls.settings('posthog-mcp')}>
                                        Set up MCP
                                    </WaysToUseSurfaceLink>
                                }
                            />
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter className="sm:justify-center">
                    <Button
                        variant="primary"
                        onClick={() => closeWaysToUse('get_started')}
                        data-attr="today-ways-to-use-get-started"
                    >
                        Get started
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
