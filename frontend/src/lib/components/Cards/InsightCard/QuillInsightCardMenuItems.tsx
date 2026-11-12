import { router } from 'kea-router'

import { DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { QuillExportSubMenu } from 'lib/components/ExportButton/QuillExportSubMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { InsightCardMenu } from './insightCardMenu'
import { QuillDashboardInsightDisplayOptionsMenu } from './QuillDashboardInsightDisplayOptionsMenu'
import { QuillInsightCardMoreSubMenu } from './QuillInsightCardMoreSubMenu'

export function QuillInsightCardMenuItems({ menu }: { menu: InsightCardMenu }): JSX.Element {
    const { view, edit, duplicate } = menu
    const removeFromDashboard = menu.dashboard?.placement?.removeFromDashboard
    // Copying a PNG is client-side, so it stays available when someone cannot create exports.
    const copyImageInExport =
        !!menu.export && !getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor)

    return (
        <>
            {edit && (
                <DropdownMenuItem
                    onClick={() => router.actions.push(edit.url)}
                    tooltip={
                        typeof edit.overrideWarning.tooltip === 'function'
                            ? edit.overrideWarning.tooltip()
                            : edit.overrideWarning.tooltip
                    }
                >
                    {edit.overrideWarning.icon}
                    Edit
                </DropdownMenuItem>
            )}
            {view && <DropdownMenuItem onClick={() => router.actions.push(view.url)}>View</DropdownMenuItem>}
            {menu.displayOptions && (
                <QuillDashboardInsightDisplayOptionsMenu
                    visualizationItems={menu.displayOptions.visualizationItems}
                    tabs={menu.displayOptions.tabs}
                />
            )}
            {duplicate && (
                <DropdownMenuItem onClick={duplicate.onClick} data-attr={duplicate.dataAttr}>
                    Duplicate
                </DropdownMenuItem>
            )}
            {menu.export && (
                <QuillExportSubMenu
                    items={menu.export.items}
                    copyToClipboardItems={[
                        ...(menu.export.copyToClipboardItems ?? []),
                        ...(copyImageInExport
                            ? [
                                  {
                                      title: 'PNG',
                                      onClick: menu.copyImage.onClick,
                                      disabledReason: menu.copyImage.disabledReason,
                                      'data-attr': 'insight-card-copy-image',
                                  },
                              ]
                            : []),
                    ]}
                />
            )}
            <QuillInsightCardMoreSubMenu menu={menu} showCopyImage={!copyImageInExport} />

            {(removeFromDashboard || menu.deleteInsight) && (
                <>
                    <DropdownMenuSeparator />
                    {removeFromDashboard && (
                        <DropdownMenuItem variant="destructive" onClick={removeFromDashboard}>
                            Remove from dashboard
                        </DropdownMenuItem>
                    )}
                    {menu.deleteInsight && (
                        <DropdownMenuItem variant="destructive" onClick={menu.deleteInsight}>
                            Delete insight
                        </DropdownMenuItem>
                    )}
                </>
            )}
        </>
    )
}
