import { useActions, useValues } from 'kea'

import { IconDownload, IconPencil, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton, Spinner, lemonToast } from '@posthog/lemon-ui'

import { downloadExportedAsset, exportedAssetBlob } from 'lib/components/ExportButton/exporter'
import { ScreenShotEditor } from 'lib/components/TakeScreenshot/ScreenShotEditor'
import { takeScreenshotLogic } from 'lib/components/TakeScreenshot/takeScreenshotLogic'
import { dayjs } from 'lib/dayjs'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { ExportedAssetType, ExporterFormat } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelExportsLogic } from './sidePanelExportsLogic'

const ROW_LIMIT_IN_THOUSANDS = 300

export const SidePanelExportsIcon = (): JSX.Element => {
    const { freshUndownloadedExports } = useValues(sidePanelExportsLogic)
    return (
        <IconWithCount count={freshUndownloadedExports.length}>
            <IconDownload />
        </IconWithCount>
    )
}

function ExportPanelHeader(): JSX.Element {
    const { assetFormat, exportsLoading } = useValues(sidePanelExportsLogic)
    const { loadExports, setAssetFormat } = useActions(sidePanelExportsLogic)

    return (
        <div className="flex justify-between items-center">
            <LemonSelect
                size="small"
                options={[
                    {
                        label: 'All',
                        value: null,
                    },
                    ...Object.entries(ExporterFormat).map(([key, value]) => ({
                        label: key,
                        value: value,
                    })),
                ]}
                value={assetFormat}
                onChange={setAssetFormat}
                disabledReason={exportsLoading ? 'Loading exports...' : undefined}
            />
            <LemonButton
                onClick={loadExports}
                type="tertiary"
                size="small"
                icon={<IconRefresh />}
                loading={exportsLoading}
            >
                Refresh
            </LemonButton>
        </div>
    )
}

function ExportRow({ asset }: { asset: ExportedAssetType }): JSX.Element {
    const { freshUndownloadedExports } = useValues(sidePanelExportsLogic)
    const { removeFresh } = useActions(sidePanelExportsLogic)
    const { setBlob } = useActions(takeScreenshotLogic({ screenshotKey: 'exports' }))

    const handleEdit = async (asset: ExportedAssetType): Promise<void> => {
        const r = await exportedAssetBlob(asset)
        if (!r) {
            lemonToast.error('Cannot get the file. Please try again.')
            return
        }
        setBlob(r)
    }

    const isNotDownloaded = freshUndownloadedExports.some((fresh) => fresh.id === asset.id)
    const stillCalculating = !asset.has_content && !asset.exception
    let disabledReason: string | undefined = undefined
    if (asset.exception) {
        disabledReason = asset.exception
    } else if (!asset.has_content) {
        disabledReason = 'Export not ready yet'
    }

    return (
        <div className="flex justify-between mt-2 gap-2 border rounded bg-fill-primary items-center">
            <div className="flex items-center justify-between flex-auto p-2">
                <div>
                    <span className="text-link font-medium block">{asset.filename}</span>
                    {asset.created_at && <span className="text-xs mt-1">{dayjs(asset.created_at).fromNow()}</span>}
                    {asset.expires_after && (
                        <span className="text-xs text-secondary mt-1">
                            {' '}
                            · expires {dayjs(asset.expires_after).fromNow()}
                        </span>
                    )}
                    {isNotDownloaded && <span className="text-xs text-secondary mt-1"> · not downloaded yet</span>}
                    {asset.export_format === ExporterFormat.CSV && (
                        <span className="text-xs text-secondary mt-1"> · {ROW_LIMIT_IN_THOUSANDS}k row limit</span>
                    )}
                </div>
            </div>
            <div className="flex gap-2 mr-2">
                {asset.export_format === ExporterFormat.PNG && (
                    <LemonButton
                        tooltip="Edit"
                        size="small"
                        disabledReason={disabledReason}
                        type={isNotDownloaded ? 'primary' : 'secondary'}
                        icon={<IconPencil />}
                        onClick={() => {
                            void handleEdit(asset)
                        }}
                    />
                )}
                <LemonButton
                    tooltip="Download"
                    size="small"
                    type={isNotDownloaded ? 'primary' : 'secondary'}
                    key={asset.id}
                    disabledReason={disabledReason}
                    onClick={() => {
                        removeFresh(asset)
                        void downloadExportedAsset(asset)
                    }}
                    sideIcon={
                        stillCalculating ? (
                            <Spinner />
                        ) : asset.has_content ? (
                            <IconDownload className="text-link" />
                        ) : (
                            <IconWarning className="text-link" />
                        )
                    }
                />
            </div>
        </div>
    )
}

const ExportsEmpty = (): JSX.Element => {
    const { assetFormat } = useValues(sidePanelExportsLogic)

    const getTTLMessage = (): string | null => {
        if (!assetFormat) {
            return 'Exports are automatically deleted after: CSV/XLSX (7 days), Video formats (12 months), Other formats (6 months)'
        }

        switch (assetFormat) {
            case ExporterFormat.CSV:
            case ExporterFormat.XLSX:
                return 'CSV and XLSX exports are automatically deleted after 7 days'
            case ExporterFormat.MP4:
            case ExporterFormat.WEBM:
            case ExporterFormat.GIF:
                return 'Video exports are automatically deleted after 12 months'
            case ExporterFormat.PNG:
            case ExporterFormat.PDF:
            case ExporterFormat.JSON:
                return 'These exports are automatically deleted after 6 months'
            default:
                return null
        }
    }

    const ttlMessage = getTTLMessage()

    return (
        <div className="flex flex-col gap-2 items-center justify-center mt-4">
            <div className="border rounded bg-fill-primary p-4 text-center">
                <p className="mb-2">No exports matching current filters</p>
                {ttlMessage && <p className="text-xs text-secondary">{ttlMessage}</p>}
            </div>
        </div>
    )
}

const ExportsContent = (): JSX.Element => {
    const { exports, exportsLoading } = useValues(sidePanelExportsLogic)

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto px-2 py-1 flex flex-col gap-2    ">
                <ExportPanelHeader />

                <ScreenShotEditor screenshotKey="exports" />
                {exportsLoading && exports.length === 0 ? (
                    <LemonSkeleton repeat={10} active={true} fade={true} />
                ) : exports.length === 0 ? (
                    <ExportsEmpty />
                ) : (
                    exports.map((asset) => {
                        return <ExportRow asset={asset} key={asset.id} />
                    })
                )}
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
