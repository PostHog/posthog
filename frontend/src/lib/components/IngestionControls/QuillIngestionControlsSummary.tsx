import { IconCheck, IconCircleDashed } from '@posthog/icons'
import { Button, Heading, Item, ItemContent, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { summaryLabel, triggerSummary } from './triggerSummary'
import { Trigger } from './types'

export function QuillIngestionControlsSummary({
    triggers,
    controlDescription,
    docsLink,
}: {
    triggers: Trigger[]
    controlDescription: string
    docsLink?: {
        to: string
        label: string
    }
}): JSX.Element {
    const hasAnyTriggers = triggers.some((t) => t.enabled)

    return (
        <Item tone="info" size="sm">
            <ItemContent className="gap-2">
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        {hasAnyTriggers ? 'Trigger summary' : `No triggers: all ${controlDescription}`}
                    </Heading>
                    {docsLink && (
                        <Text size="xs" render={<p className="m-0" />}>
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={docsLink.to} target="_blank" />}
                            >
                                {docsLink.label}
                            </Button>
                        </Text>
                    )}
                </div>
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                    {triggers.map((trigger, i) => (
                        <li key={i} className="flex items-center gap-2">
                            {trigger.enabled ? (
                                <IconCheck className="shrink-0 text-success-foreground" />
                            ) : (
                                <IconCircleDashed className="shrink-0 text-muted-foreground" />
                            )}
                            <Text size="xs" variant={trigger.enabled ? 'default' : 'muted'} render={<span />}>
                                {summaryLabel[trigger.type]}
                                {trigger.enabled && (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {' '}
                                        ({triggerSummary(trigger)})
                                    </Text>
                                )}
                            </Text>
                        </li>
                    ))}
                </ul>
            </ItemContent>
        </Item>
    )
}
