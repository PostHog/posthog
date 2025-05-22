import { IconDownload, IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { downloadExportedAsset } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { IconRefresh, IconWithCount } from 'lib/lemon-ui/icons'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelExportsLogic } from './sidePanelExportsLogic'

export const SidePanelExportsIcon = (): JSX.Element => {
    const { freshUndownloadedExports } = useValues(sidePanelExportsLogic)
    return (
        <IconWithCount count={freshUndownloadedExports.length}>
            <IconDownload />
        </IconWithCount>
    )
}

const ExportsContent = (): JSX.Element => {
    const { exports, freshUndownloadedExports } = useValues(sidePanelExportsLogic)
    const { loadExports, removeFresh } = useActions(sidePanelExportsLogic)

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-2">
                <div className="flex justify-end">
                    <LemonButton onClick={loadExports} type="tertiary" size="small" icon={<IconRefresh />}>
                        Refresh
                    </LemonButton>
                </div>

                {exports.map((asset) => {
                    const isNotDownloaded = freshUndownloadedExports.some((fresh) => fresh.id === asset.id)
                    const stillCalculating = !asset.has_content && !asset.exception
                    let disabledReason: string | undefined = undefined
                    if (asset.exception) {
                        disabledReason = asset.exception
                    } else if (!asset.has_content) {
                        disabledReason = 'Export not ready yet'
                    }

                    return (
                        <LemonButton
                            type={isNotDownloaded ? 'primary' : 'secondary'}
                            key={asset.id}
                            fullWidth
                            className="mt-2"
                            disabledReason={disabledReason}
                            onClick={() => {
                                removeFresh(asset)
                                void downloadExportedAsset(asset)
                            }}
                            sideIcon={asset.has_content ? <IconDownload className="text-link" /> : undefined}
                        >
                            <div className="flex items-center justify-between flex-auto p-2">
                                <div>
                                    <span className="text-link font-medium block">{asset.filename}</span>
                                    {asset.created_at && (
                                        <span className="text-xs mt-1">{dayjs(asset.created_at).fromNow()}</span>
                                    )}
                                    {asset.expires_after && (
                                        <span className="text-xs text-secondary mt-1">
                                            {' '}
                                            · expires {dayjs(asset.expires_after).fromNow()}
                                        </span>
                                    )}
                                    {isNotDownloaded && (
                                        <span className="text-xs text-secondary mt-1"> · not downloaded yet</span>
                                    )}
                                </div>
                                <div>{stillCalculating && <Spinner />}</div>
                                <div>{asset.exception && <IconWarning className="text-link" />}</div>
                            </div>
                        </LemonButton>
                    )
                })}
            </div>
        </div>
    )
}

export const SidePanelExports = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelPaneHeader
                title={
                    <div className="flex deprecated-space-x-2">
                        <span>Exports</span>
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
