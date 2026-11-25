import { Heading, Text } from '@posthog/quill'

import { QuillMinDurationTrigger } from 'lib/components/IngestionControls/triggers/QuillMinDurationTrigger'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AvailableFeature } from '~/types'

import { QuillSince } from './QuillSince'

export function QuillMobileMinimumDuration({
    value,
    onChange,
}: {
    value: number | null | undefined
    onChange: (value: number | null | undefined) => void
}): JSX.Element {
    return (
        <PayGateMini
            feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}
            featureDetail="replay-minimum-recording-duration"
        >
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                        Duration threshold
                        <QuillSince
                            ios={{ version: '3.53.0' }}
                            android={{ version: '3.44.0' }}
                            reactNative={{ version: '4.52.0' }}
                            flutter={{ version: '5.24.3' }}
                        />
                    </Heading>
                    <QuillMinDurationTrigger value={value} onChange={onChange} />
                </div>
                <Text size="xs" render={<p className="m-0" />}>
                    Only collect sessions that last longer than this. This helps you avoid recording sessions that are
                    too short to be useful.
                </Text>
            </div>
        </PayGateMini>
    )
}
