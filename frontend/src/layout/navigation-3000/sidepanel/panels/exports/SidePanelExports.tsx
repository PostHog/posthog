import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { downloadExportedAsset } from 'lib/components/ExportButton/exporter'
import { IconCheckmark, IconRefresh, IconWithCount } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { useEffect } from 'react'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelExportsLogic } from './sidePanelExportsLogic'

export const SidePanelExportsIcon = (props: { className?: string }): JSX.Element => {
    const { exports } = useValues(sidePanelExportsLogic)

    return (
        <IconWithCount count={exports?.length} {...props}>
            <IconDownload />
        </IconWithCount>
    )
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
                        status="alt"
                        key={asset.id}
                        fullWidth
                        className="mt-2"
                        onClick={() => {
                            void downloadExportedAsset(asset)
                        }}
                    >
                        <div className="flex items-center justify-between w-full">
                            <div className="flex flex-col">
                                <span className="text-sm font-medium">
                                    <LemonTag size="small" className="mr-2">
                                        {asset.export_format}
                                    </LemonTag>
                                    {asset.filename}
                                </span>
                                {asset.expires_after && (
                                    <span className="text-xs mt-1">
                                        Available until {humanFriendlyDetailedTime(asset.expires_after)}
                                    </span>
                                )}
                            </div>
                            <div>{asset.has_content ? <IconCheckmark /> : <Spinner />}</div>
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
