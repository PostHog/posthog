import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Spinner,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { useInstallationComplete } from '../../control/sdks/hooks/useInstallationComplete'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

function ChecklistItem({
    status,
    title,
    mono = false,
    children,
}: {
    status: 'done' | 'waiting' | 'todo'
    title: string
    /** Event names read as code. */
    mono?: boolean
    children?: React.ReactNode
}): JSX.Element {
    return (
        <Item size="sm" className="px-0">
            <ItemMedia variant="icon">
                {status === 'done' ? (
                    <IconCheckCircle className="text-success-foreground" />
                ) : status === 'waiting' ? (
                    <Spinner />
                ) : (
                    <span className="size-3.5 rounded-full border-2 border-border" />
                )}
            </ItemMedia>
            <ItemContent>
                <ItemTitle
                    className={cn(mono && 'font-mono', status === 'done' && 'text-muted-foreground line-through')}
                >
                    {title}
                </ItemTitle>
                {children && <ItemDescription>{children}</ItemDescription>}
            </ItemContent>
        </Item>
    )
}

function SeenAt({ prefix, timestamp }: { prefix: string; timestamp: string }): JSX.Element {
    return (
        <span>
            <span translate="no">{prefix}</span> <TZLabel time={timestamp} />
        </span>
    )
}

export function InstallChecklist(): JSX.Element {
    const { trackedEvents, trackedLastSeen, latestEvent } = useValues(guidedOnboardingLogic)
    const firstEventReceived = useInstallationComplete('ingested_event')

    return (
        <Card data-attr="guided-onboarding-install-checklist">
            <CardHeader>
                <CardDescription>Installation</CardDescription>
            </CardHeader>
            <CardContent>
                <ItemGroup combined>
                    <ChecklistItem
                        status={firstEventReceived ? 'done' : 'waiting'}
                        title="Install the SDK and send a first event"
                    >
                        {latestEvent ? (
                            <SeenAt prefix={`Latest: ${latestEvent.event},`} timestamp={latestEvent.timestamp} />
                        ) : (
                            !firstEventReceived && 'Listening for events'
                        )}
                    </ChecklistItem>
                    {trackedEvents.map((event) => (
                        <ChecklistItem key={event} status={trackedLastSeen[event] ? 'done' : 'todo'} title={event} mono>
                            {trackedLastSeen[event] ? (
                                <SeenAt prefix="Last seen" timestamp={trackedLastSeen[event]} />
                            ) : (
                                'Not captured yet'
                            )}
                        </ChecklistItem>
                    ))}
                    <ChecklistItem status="todo" title="Deploy the changes to production" />
                </ItemGroup>
            </CardContent>
        </Card>
    )
}
