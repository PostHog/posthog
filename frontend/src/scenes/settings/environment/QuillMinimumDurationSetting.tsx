import { Heading, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillMinDurationTrigger } from 'lib/components/IngestionControls/triggers/QuillMinDurationTrigger'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AvailableFeature } from '~/types'

import { QuillSince } from './QuillSince'

export function QuillMinimumDurationSetting({
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
                        Duration threshold <QuillSince web={{ version: '1.85.0' }} ios={{ version: '3.53.0' }} />
                    </Heading>
                    <QuillMinDurationTrigger value={value} onChange={onChange} />
                </div>
                <Text size="xs" render={<p className="m-0" />}>
                    <Tooltip>
                        <TooltipTrigger render={<span className="cursor-help" />}>
                            Setting a minimum session duration will ensure that only sessions that last longer than that
                            value are collected. This helps you avoid collecting sessions that are too short to be
                            useful.
                        </TooltipTrigger>
                        <TooltipContent className="max-w-80">
                            <div className="flex flex-col gap-1">
                                <span>
                                    The JS SDK has an in-memory queue. This means that for traditional web apps the
                                    minimum duration control is best effort.
                                </span>
                                <LinkPrimitive
                                    to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations"
                                    target="_blank"
                                    className="text-xs text-primary-on-foreground underline"
                                    data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                                    data-ph-capture-attribute-doclink="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations"
                                >
                                    Read the docs
                                </LinkPrimitive>
                            </div>
                        </TooltipContent>
                    </Tooltip>
                </Text>
            </div>
        </PayGateMini>
    )
}
