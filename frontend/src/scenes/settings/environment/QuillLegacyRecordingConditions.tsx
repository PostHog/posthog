import { ReactNode } from 'react'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Heading } from '@posthog/quill'

import { QuillMatchTypeSelect } from 'lib/components/IngestionControls/QuillMatchTypeSelect'

import { QuillSince } from './QuillSince'
import { QuillTriggerPanelHeader } from './QuillTriggerPanelHeader'

export function QuillLegacyRecordingConditions({
    statuses,
    summary,
    samplingWarning,
    urlTriggerOptions,
    eventTriggerOptions,
    linkedFlagSelector,
    sampling,
    minimumDuration,
}: {
    statuses: {
        urlStatus: string
        eventStatus: string
        flagStatus: string
        samplingStatus: string
        minDurationStatus: string
    }
    summary: ReactNode
    samplingWarning: ReactNode
    urlTriggerOptions: ReactNode
    eventTriggerOptions: ReactNode
    linkedFlagSelector: ReactNode
    sampling: ReactNode
    minimumDuration: ReactNode
}): JSX.Element {
    return (
        <>
            {summary}

            <QuillMatchTypeSelect titleBadge={<QuillSince web={{ version: '1.238.0' }} />} />

            {samplingWarning}

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Recording conditions
                </Heading>
                <Accordion multiple>
                    <AccordionItem value="url">
                        <AccordionTrigger>
                            <QuillTriggerPanelHeader title="URL matches" status={statuses.urlStatus} showMatchTag />
                        </AccordionTrigger>
                        <AccordionContent>{urlTriggerOptions}</AccordionContent>
                    </AccordionItem>
                    <AccordionItem value="event">
                        <AccordionTrigger>
                            <QuillTriggerPanelHeader title="Event emitted" status={statuses.eventStatus} showMatchTag />
                        </AccordionTrigger>
                        <AccordionContent>{eventTriggerOptions}</AccordionContent>
                    </AccordionItem>
                    <AccordionItem value="flag">
                        <AccordionTrigger>
                            <QuillTriggerPanelHeader title="Feature flag" status={statuses.flagStatus} showMatchTag />
                        </AccordionTrigger>
                        <AccordionContent>{linkedFlagSelector}</AccordionContent>
                    </AccordionItem>
                </Accordion>
            </div>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Recording limits
                </Heading>
                <Accordion multiple>
                    <AccordionItem value="sampling">
                        <AccordionTrigger>
                            <QuillTriggerPanelHeader title="Sampling" status={statuses.samplingStatus} showMatchTag />
                        </AccordionTrigger>
                        <AccordionContent>{sampling}</AccordionContent>
                    </AccordionItem>
                    <AccordionItem value="min-duration">
                        <AccordionTrigger>
                            <QuillTriggerPanelHeader title="Minimum duration" status={statuses.minDurationStatus} />
                        </AccordionTrigger>
                        <AccordionContent>{minimumDuration}</AccordionContent>
                    </AccordionItem>
                </Accordion>
            </div>
        </>
    )
}
