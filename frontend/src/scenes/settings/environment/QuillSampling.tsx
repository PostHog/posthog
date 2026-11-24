import { ComponentProps } from 'react'

import { Heading, Text } from '@posthog/quill'

import { QuillSamplingTrigger } from 'lib/components/IngestionControls/triggers/QuillSamplingTrigger'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ReplayPlatform } from 'scenes/settings/environment/replayTriggersLogic'

import { AvailableFeature } from '~/types'

import { QuillSince } from './QuillSince'

const PLATFORM_SDK_VERSIONS: Record<ReplayPlatform, ComponentProps<typeof QuillSince>> = {
    web: {
        web: { version: '1.85.0' },
        android: { version: '3.34.0' },
        ios: { version: '3.42.0' },
        reactNative: { version: '4.37.0' },
    },
    mobile: {
        android: { version: '3.34.0' },
        ios: { version: '3.42.0' },
        reactNative: { version: '4.37.0' },
    },
}

export function QuillSampling({
    platform,
    isDefault,
    initialSampleRate,
    onChange,
}: {
    platform: ReplayPlatform
    isDefault: boolean
    initialSampleRate: number
    onChange: (value: number) => void
}): JSX.Element {
    return (
        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING} featureDetail="session-replay-sampling">
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                        Sample rate
                        <QuillSince {...PLATFORM_SDK_VERSIONS[platform]} />
                        {isDefault && (
                            <Text size="xs" variant="muted" render={<span className="m-0 font-normal" />}>
                                (default)
                            </Text>
                        )}
                    </Heading>
                    <QuillSamplingTrigger initialSampleRate={initialSampleRate} onChange={onChange} />
                </div>
                <Text size="xs" render={<p className="m-0" />}>
                    Choose how many sessions to record. 100% = record every session, 50% = record roughly half.
                </Text>
            </div>
        </PayGateMini>
    )
}
