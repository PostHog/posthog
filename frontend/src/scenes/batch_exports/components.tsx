import { LemonTag } from '@posthog/lemon-ui'
import { BatchExportConfiguration } from '~/types'

export function BatchExportTag({ batchExportConfig }: { batchExportConfig: BatchExportConfiguration }): JSX.Element {
    return (
        <LemonTag type={batchExportConfig.paused ? 'default' : 'primary'} className="uppercase">
            {batchExportConfig.paused ? 'Paused' : 'Active'}
        </LemonTag>
    )
}
