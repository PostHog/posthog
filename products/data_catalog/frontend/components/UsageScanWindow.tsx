import { Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { UsageSnapshotApi } from '../generated/api.schemas'

export function UsageScanWindow({ scan }: { scan: UsageSnapshotApi }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<p className="m-0" />}>
            Usage from <TZLabel time={scan.window_start} /> to <TZLabel time={scan.window_end} />
            {scan.computed_at && (
                <>
                    , scanned <TZLabel time={scan.computed_at} />
                </>
            )}
            .
        </Text>
    )
}
