import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { downloadExportedAsset } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelExportsLogic } from './sidePanelExportsLogic'

export const SidePanelExportsIcon = (): JSX.Element => {
    return <IconDownload />
}

const ExportsContent = (): JSX.Element => {
    const { exports } = useValues(sidePanelExportsLogic)
    const { loadExports } = useActions(sidePanelExportsLogic)

    useEffect(() => {
        loadExports()
    }, [])

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-2">
                <div className="flex justify-end">
                    <LemonButton onClick={loadExports} type="tertiary" size="small" icon={<IconRefresh />}>
                        Refresh
                    </LemonButton>
                </div>

                {exports.map((asset) => (
                    <LemonButton
                        type="secondary"
                        key={asset.id}
                        fullWidth
                        className="mt-2"
                        disabledReason={!asset.has_content ? 'Export not ready yet' : undefined}
                        onClick={() => {
                            void downloadExportedAsset(asset)
                        }}
                        sideIcon={asset.has_content ? <IconDownload className="text-link" /> : undefined}
                    >
                        <div className="flex items-center justify-between flex-auto p-2">
                            <div>
                                <span className="text-link font-medium block">
                                    {asset.filename}
                                    <LemonTag size="small" className="ml-2">
                                        {asset.export_format}
                                    </LemonTag>
                                </span>
                                {asset.expires_after && (
                                    <span className="text-xs text-muted mt-1">
                                        Expires {dayjs(asset.expires_after).fromNow()}
                                    </span>
                                )}
                            </div>
                            <div>{!asset.has_content && <Spinner />}</div>
                        </div>
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}

export const SidePanelExports = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelPaneHeader
                title={
                    <div className="flex space-x-2">
                        <span>Exports</span>
                        <Tooltip title="While exports are not new, this side panel is a feature we are experimenting with! We'd love to get your feedback on it and whether this is something useful for working with PostHog.">
                            <LemonTag type="completion">Experimental</LemonTag>
                        </Tooltip>
                    </div>
                }
            />
            <p className="m-4">
                Retrieve your exports here. Exports are generated asynchronously and may take a few seconds to complete.
            </p>
            <ExportsContent />
        </div>
    )
}
