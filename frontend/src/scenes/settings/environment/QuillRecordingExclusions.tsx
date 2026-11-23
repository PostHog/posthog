import { ReactNode } from 'react'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Heading, Text } from '@posthog/quill'

import { QuillSince } from './QuillSince'
import { QuillTriggerPanelHeader } from './QuillTriggerPanelHeader'

export function QuillRecordingExclusions({
    blocklistStatus,
    urlBlocklistOptions,
}: {
    blocklistStatus: string
    urlBlocklistOptions: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0 flex items-center gap-1" />}>
                    Recording exclusions <QuillSince web={{ version: '1.171.0' }} />
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    The URL blocklist is global. It applies to trigger groups and to the legacy recording conditions.
                </Text>
            </div>
            <Accordion multiple>
                <AccordionItem value="blocklist">
                    <AccordionTrigger>
                        <QuillTriggerPanelHeader title="URL blocklist" status={blocklistStatus} />
                    </AccordionTrigger>
                    <AccordionContent>{urlBlocklistOptions}</AccordionContent>
                </AccordionItem>
            </Accordion>
        </div>
    )
}
