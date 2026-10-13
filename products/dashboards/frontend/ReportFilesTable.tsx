import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { getEntryAccessDisabledReason } from 'lib/utils/accessControlUtils'

import { getFileSystemIconType, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { moveToLogic } from '~/lib/components/FileSystem/MoveTo/moveToLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { reportsLogic } from './reportsLogic'

export function ReportFilesTable({
    folder,
    loading,
    teamId,
}: {
    folder: string
    loading: boolean
    teamId: number | null
}): JSX.Element {
    const { fileEntries, currentFolder, folderContext, savedContextLoading, searchTerm, fileType } = useValues(
        reportsLogic({ folder, teamId })
    )
    const { pinDashboard } = useActions(reportsLogic({ folder, teamId }))
    const { openMoveToModal } = useActions(moveToLogic)
    return (
        <LemonTable<FileSystemEntry>
            dataSource={fileEntries}
            loading={loading}
            rowKey="id"
            pagination={{ pageSize: 20 }}
            emptyState={
                searchTerm || fileType !== 'all'
                    ? 'No files match these filters. Try another search or file type.'
                    : 'No files here yet. Create a dashboard or move an existing file into this folder.'
            }
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    sorter: (a, b) => a.path.localeCompare(b.path),
                    render: (_, entry) => (
                        <div className="flex items-center gap-2 min-w-0 group/colorful-product-icons colorful-product-icons-true">
                            <span className="text-xl shrink-0">{iconForType(getFileSystemIconType(entry))}</span>
                            <div className="flex-1 min-w-0">
                                <LemonButton
                                    to={entry.href}
                                    fullWidth
                                    disabledReason={getEntryAccessDisabledReason(entry)}
                                >
                                    {splitPath(entry.path).at(-1)}
                                </LemonButton>
                            </div>
                            {folderContext.pinned_dashboard_id === Number(entry.ref) && entry.type === 'dashboard' && (
                                <IconPinFilled className="text-secondary shrink-0" />
                            )}
                        </div>
                    ),
                },
                {
                    title: 'Type',
                    key: 'type',
                    width: 100,
                    render: (_, entry) => (
                        <LemonTag>
                            {entry.type === 'dashboard'
                                ? 'Dashboard'
                                : entry.type === 'insight'
                                  ? 'Insight'
                                  : entry.type === 'notebook'
                                    ? 'Notebook'
                                    : 'File'}
                        </LemonTag>
                    ),
                },
                {
                    title: '',
                    key: 'actions',
                    width: 48,
                    render: (_, entry) => (
                        <LemonMenu
                            items={[
                                ...(currentFolder && entry.type === 'dashboard' && entry.ref
                                    ? [
                                          {
                                              label:
                                                  folderContext.pinned_dashboard_id === Number(entry.ref)
                                                      ? 'Unpin dashboard'
                                                      : 'Pin for this folder',
                                              icon: <IconPin />,
                                              onClick: () =>
                                                  pinDashboard(
                                                      folderContext.pinned_dashboard_id === Number(entry.ref)
                                                          ? null
                                                          : Number(entry.ref)
                                                  ),
                                              disabledReason: savedContextLoading
                                                  ? 'Saving pinned dashboard'
                                                  : getEntryAccessDisabledReason(entry),
                                              'data-attr': 'reports-pin-dashboard',
                                          },
                                      ]
                                    : []),
                                {
                                    label: 'Move to folder',
                                    onClick: () => openMoveToModal([entry]),
                                    disabledReason: getEntryAccessDisabledReason(entry),
                                    'data-attr': 'reports-move-file',
                                },
                            ]}
                        >
                            <LemonButton
                                icon={<IconEllipsis />}
                                size="small"
                                aria-label={`Actions for ${splitPath(entry.path).at(-1)}`}
                                data-attr="reports-file-actions"
                            />
                        </LemonMenu>
                    ),
                },
            ]}
        />
    )
}
