import { AnimationType } from 'lib/animations/animations'
import api from 'lib/api'
import { Animation } from 'lib/components/Animation/Animation'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { delay } from 'lib/utils'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { ExportContext, ExportedAssetType, ExporterFormat, LocalExportContext } from '~/types'

const POLL_DELAY_MS = 1000
const MAX_PNG_POLL = 10
const MAX_CSV_POLL = 300

function downloadBlob(content: Blob, filename: string): void {
    const anchor = document.createElement('a')
    anchor.style.display = 'none'
    const objectURL = window.URL.createObjectURL(content)
    anchor.href = objectURL
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    window.URL.revokeObjectURL(objectURL)
}

async function downloadExportedAsset(asset: ExportedAssetType): Promise<void> {
    const downloadUrl = api.exports.determineExportUrl(asset.id)
    const response = await api.getResponse(downloadUrl)
    const blobObject = await response.blob()
    downloadBlob(blobObject, asset.filename)
}

export type TriggerExportProps = Pick<ExportedAssetType, 'export_format' | 'dashboard' | 'insight' | 'export_context'>

const isLocalExport = (context: ExportContext | undefined): context is LocalExportContext =>
    !!(context && 'localData' in context)

export async function triggerExport(asset: TriggerExportProps): Promise<void> {
    if (isLocalExport(asset.export_context)) {
        try {
            downloadBlob(
                new Blob([asset.export_context.localData], { type: asset.export_context.mediaType }),
                asset.export_context.filename
            )
            lemonToast.success('Export complete!')
        } catch (e) {
            lemonToast.error('Export failed!')
        }
    } else {
        // eslint-disable-next-line no-async-promise-executor,@typescript-eslint/no-misused-promises
        const poller = new Promise<string>(async (resolve, reject) => {
            const trackingProperties = {
                export_format: asset.export_format,
                dashboard: asset.dashboard,
                insight: asset.insight,
                export_context: asset.export_context,
                total_time_ms: 0,
            }
            const startTime = performance.now()

            try {
                let exportedAsset = await api.exports.create({
                    export_format: asset.export_format,
                    dashboard: asset.dashboard,
                    insight: asset.insight,
                    export_context: asset.export_context,
                    expires_after: dayjs().add(10, 'minute'),
                })

                if (!exportedAsset.id) {
                    reject('Missing export_id from response')
                    return
                }

                let attempts = 0

                const maxPoll = asset.export_format === ExporterFormat.CSV ? MAX_CSV_POLL : MAX_PNG_POLL
                while (attempts < maxPoll) {
                    attempts++

                    if (exportedAsset.has_content) {
                        await downloadExportedAsset(exportedAsset)

                        trackingProperties.total_time_ms = performance.now() - startTime
                        posthog.capture('export succeeded', trackingProperties)

                        resolve('Export complete')
                        return
                    }

                    await delay(POLL_DELAY_MS)

                    // Keep polling for pure network errors like network down, but not any HTTP errors
                    try {
                        exportedAsset = await api.exports.get(exportedAsset.id)
                    } catch (e: any) {
                        if (e.name === 'NetworkError') {
                            continue
                        }
                        throw e
                    }
                }

                reject('Content not loaded in time...')
            } catch (e: any) {
                trackingProperties.total_time_ms = performance.now() - startTime
                posthog.capture('export failed', trackingProperties)
                reject(`Export failed: ${JSON.stringify(e)}`)
            }
        })
        await lemonToast.promise(
            poller,
            {
                pending: <DelayedContent atStart="Export starting..." afterDelay="Waiting for export..." />,
                success: 'Export complete!',
                error: 'Export failed!',
            },
            {
                pending: (
                    <DelayedContent
                        atStart={<Spinner />}
                        afterDelay={<Animation size="small" type={AnimationType.SportsHog} />}
                    />
                ),
            }
        )
    }
}

interface DelayedContentProps {
    atStart: JSX.Element | string
    afterDelay: JSX.Element | string
}

function DelayedContent({ atStart, afterDelay }: DelayedContentProps): JSX.Element {
    const [content, setContent] = useState<JSX.Element | string>(atStart)
    useEffect(() => {
        setTimeout(() => {
            setContent(afterDelay)
        }, 30000)
    }, [])
    return <>{content}</>
}
