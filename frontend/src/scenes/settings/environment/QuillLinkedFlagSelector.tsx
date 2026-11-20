import { Heading, Text } from '@posthog/quill'

import IngestionControls from 'lib/components/IngestionControls'
import { QuillFlagTriggerSelector } from 'lib/components/IngestionControls/triggers/FlagTrigger/QuillFlagTriggerSelector'
import { QuillFlagTriggerVariantSelector } from 'lib/components/IngestionControls/triggers/FlagTrigger/QuillFlagTriggerVariantSelector'
import { LinkedFeatureFlag } from 'lib/components/IngestionControls/types'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AvailableFeature } from '~/types'

import { QuillSince } from './QuillSince'

export function QuillLinkedFlagSelector({
    flag,
    onChange,
}: {
    flag: LinkedFeatureFlag | null
    onChange: (flag: LinkedFeatureFlag | null) => void
}): JSX.Element {
    return (
        <PayGateMini
            feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}
            featureDetail="replay-feature-flag-trigger"
        >
            <IngestionControls.FlagTrigger logicKey="session-replay-linked-flag" flag={flag} onChange={onChange}>
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                            Select feature flag
                            <QuillSince
                                web={{ version: '1.110.0' }}
                                ios={{ version: '3.11.0' }}
                                android={{ version: '3.11.0' }}
                                reactNative={{ version: '3.6.3' }}
                                flutter={{ version: '4.7.0' }}
                            />
                        </Heading>
                        <QuillFlagTriggerSelector />
                    </div>
                    <Text size="xs" render={<p className="m-0" />}>
                        Only record when this flag is enabled. <strong>Shared across web and mobile.</strong>
                    </Text>
                    <QuillFlagTriggerVariantSelector
                        tooltip={
                            <>
                                <span>Record for "any" variant, or only for a specific variant.</span>
                                <span>Variant targeting requires posthog-js v1.110.0+</span>
                            </>
                        }
                    />
                </div>
            </IngestionControls.FlagTrigger>
        </PayGateMini>
    )
}
