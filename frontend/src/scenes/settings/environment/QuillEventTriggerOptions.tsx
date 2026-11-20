import { ComponentProps } from 'react'

import { Heading, Text } from '@posthog/quill'

import { QuillEventTrigger } from 'lib/components/IngestionControls/triggers/QuillEventTrigger'
import { QuillEventTriggerSelect } from 'lib/components/IngestionControls/triggers/QuillEventTriggerSelect'
import { ReplayPlatform } from 'scenes/settings/environment/replayTriggersLogic'

import { QuillSince } from './QuillSince'

const PLATFORM_HEADINGS: Record<ReplayPlatform, { title: string; sdkVersions: ComponentProps<typeof QuillSince> }> = {
    web: {
        title: 'Select events',
        sdkVersions: { web: { version: '1.186.0' } },
    },
    mobile: {
        title: 'Event emitted',
        sdkVersions: {
            ios: { version: '3.48.0' },
            android: { version: '3.40.1' },
            reactNative: { version: '4.52.0' },
            flutter: { version: '5.25.0' },
        },
    },
}

export function QuillEventTriggerOptions({
    platform,
    events,
    onChange,
}: {
    platform: ReplayPlatform
    events: string[] | null
    onChange: (events: string[]) => void
}): JSX.Element {
    const { title, sdkVersions } = PLATFORM_HEADINGS[platform]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                    {title}
                    <QuillSince {...sdkVersions} />
                </Heading>
                <QuillEventTriggerSelect events={events} onChange={onChange} />
            </div>
            <Text size="xs" render={<p className="m-0" />}>
                Start recording when a PostHog event is queued.
            </Text>
            <div className="flex gap-2 flex-wrap">
                {events?.map((trigger) => (
                    <QuillEventTrigger
                        key={trigger}
                        trigger={trigger}
                        onClose={() => onChange(events?.filter((e) => e !== trigger))}
                    />
                ))}
            </div>
        </div>
    )
}
