import { IconDownload } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface TraceExportButtonProps {
    loading: boolean
    onExport: () => void
    disabledReason?: string
}

export function TraceExportButton({ loading, onExport, disabledReason }: TraceExportButtonProps): JSX.Element {
    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconDownload />}
            loading={loading}
            onClick={onExport}
            disabledReason={disabledReason}
            tooltip="Export this trace as a JSON file"
            data-attr="trace-view-export"
        />
    )
}
