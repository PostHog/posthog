import { useActions, useValues } from 'kea'

import { IconDownload, IconPencil, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTable, LemonTag, Spinner, lemonToast } from '@posthog/lemon-ui'
import { LemonTableColumns } from '@posthog/lemon-ui'

import { downloadExportedAsset, exportedAssetBlob } from 'lib/components/ExportButton/exporter'
import { takeScreenshotLogic } from 'lib/components/TakeScreenshot/takeScreenshotLogic'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { sidePanelExportsLogic } from '~/layout/navigation-3000/sidepanel/panels/exports/sidePanelExportsLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ExportedAssetType, ExporterFormat } from '~/types'

import { exportsSceneLogic } from './exportsSceneLogic'

const ROW_LIMIT_IN_THOUSANDS = 300

export const scene: SceneExport = {
    component: ExportsScene,
    logic: exportsSceneLogic,
}

function ExportActions({ asset }: { asset: ExportedAssetType }): JSX.Element {
    const { freshUndownloadedExports } = useValues(sidePanelExportsLogic)
    const { removeFresh } = useActions(sidePanelExportsLogic)
    const { setBlob } = useActions(takeScreenshotLogic({ screenshotKey: 'exports' }))

    const isNotDownloaded = freshUndownloadedExports.some((fresh) => fresh.id === asset.id)
    const stillCalculating = !asset.has_content && !asset.exception
    let disabledReason: string | undefined = undefined
    if (asset.exception) {
        disabledReason = asset.exception
    } else if (!asset.has_content) {
        disabledReason = 'Export not ready yet'
    }

    const handleEdit = async (): Promise<void> => {
        const r = await exportedAssetBlob(asset)
        if (!r) {
            lemonToast.error('Cannot get the file. Please try again.')
            return
        }
        setBlob(r)
    }

    return (
        <div className="flex gap-2 justify-end">
            {asset.export_format === ExporterFormat.PNG && (
                <LemonButton
                    tooltip="Edit"
                    size="xsmall"
                    data-attr="export-editor"
                    disabledReason={disabledReason}
                    type={isNotDownloaded ? 'primary' : 'secondary'}
                    icon={<IconPencil />}
                    onClick={() => {
                        void handleEdit()
                    }}
                />
            )}
            <LemonButton
                tooltip="Download"
                size="xsmall"
                type={isNotDownloaded ? 'primary' : 'secondary'}
                data-attr="export-download"
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
    )
}

export function ExportsScene(): JSX.Element {
    const { exports, exportsLoading, assetFormat } = useValues(sidePanelExportsLogic)
    const { loadExports, setAssetFormat } = useActions(sidePanelExportsLogic)

    const columns: LemonTableColumns<ExportedAssetType> = [
        {
            title: 'Filename',
            dataIndex: 'filename',
            render: (_, asset) => <span className="font-medium">{asset.filename}</span>,
        },
        {
            title: 'Format',
            dataIndex: 'export_format',
            render: (_, asset) => (
                <div className="flex items-center gap-1">
                    <LemonTag>{asset.export_format}</LemonTag>
                    {asset.export_format === ExporterFormat.CSV && (
                        <span className="text-xs text-secondary">
                            {asset.export_context?.row_limit
                                ? humanFriendlyNumber(asset.export_context.row_limit)
                                : `${ROW_LIMIT_IN_THOUSANDS}k`}{' '}
                            row limit
                        </span>
                    )}
                </div>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (_, asset) => (asset.created_at ? dayjs(asset.created_at).fromNow() : '–'),
            sorter: (a, b) => dayjs(a.created_at).unix() - dayjs(b.created_at).unix(),
        },
        {
            title: 'Expires',
            dataIndex: 'expires_after',
            render: (_, asset) => (asset.expires_after ? dayjs(asset.expires_after).fromNow() : '–'),
        },
        {
            title: '',
            width: 0,
            render: (_, asset) => <ExportActions asset={asset} />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Exports].name}
                description={sceneConfigurations[Scene.Exports].description}
                resourceType={{ type: 'exports' }}
                actions={
                    <LemonButton
                        onClick={loadExports}
                        type="primary"
                        size="small"
                        icon={<IconRefresh />}
                        loading={exportsLoading}
                        data-attr="export-refresh"
                    >
                        Refresh
                    </LemonButton>
                }
            />

            <div className="flex justify-end mb-2">
                <div className="flex items-center gap-2">
                    <span className="text-sm">Format</span>
                    <LemonSelect
                        size="small"
                        options={[
                            { label: 'All', value: null },
                            ...Object.entries(ExporterFormat).map(([key, value]) => ({
                                label: key,
                                value: value,
                            })),
                        ]}
                        value={assetFormat}
                        onChange={setAssetFormat}
                        disabledReason={exportsLoading ? 'Loading exports...' : undefined}
                    />
                </div>
            </div>

            <LemonTable
                columns={columns}
                dataSource={exports}
                loading={exportsLoading}
                rowKey="id"
                emptyState="No exports matching current filters"
                defaultSorting={{ columnKey: 'created_at', order: -1 }}
            />
        </SceneContent>
    )
}
