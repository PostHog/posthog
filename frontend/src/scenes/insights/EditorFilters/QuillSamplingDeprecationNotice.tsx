import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import type { SamplingNoticeProps } from './SamplingDeprecationNotice'

export function QuillSamplingDeprecationNotice({
    samplingFactor,
    onDisableSampling,
}: SamplingNoticeProps): JSX.Element {
    return (
        <Item variant="outline" tone="warning" size="sm">
            <ItemContent>
                <ItemDescription>
                    This insight currently uses {(samplingFactor * 100).toFixed(0)}% sampling. Sampling is being
                    deprecated and will be removed in a future release.{' '}
                    <Button variant="link" size="inline" onClick={onDisableSampling}>
                        Disable it now
                    </Button>{' '}
                    and run on full data.
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
