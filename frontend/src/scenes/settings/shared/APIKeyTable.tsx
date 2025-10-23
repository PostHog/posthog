import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { detailedTime, humanFriendlyDetailedTime } from 'lib/utils'

export interface APIKeyTableRow {
    id: string
    label: string
    mask_value?: string | null
    scopes: string[]
    created_at: string
    created_by?: {
        email: string
        first_name: string
    } | null
    last_used_at: string | null
    last_rolled_at: string | null
}

interface APIKeyTableProps {
    keys: APIKeyTableRow[]
    loading: boolean
    onEdit: (id: string) => void
    onRoll: (id: string) => void
    onDelete: (id: string) => void
    noun: string
    showCreatedBy?: boolean
    showActions?: boolean
}

function TagList({ tags, onMoreClick }: { tags: string[]; onMoreClick: () => void }): JSX.Element {
    return (
        <span className="flex flex-wrap gap-1">
            {tags.slice(0, 4).map((x) => (
                <LemonTag key={x}>{x}</LemonTag>
            ))}
            {tags.length > 4 && (
                <Tooltip title={tags.slice(4).join(', ')}>
                    <LemonTag onClick={onMoreClick}>+{tags.length - 4} more</LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

export function APIKeyTable({
    keys,
    loading,
    onEdit,
    onRoll,
    onDelete,
    noun,
    showCreatedBy = false,
    showActions = false,
}: APIKeyTableProps): JSX.Element {
    const columns: any[] = [
        {
            title: 'Label',
            dataIndex: 'label',
            key: 'label',
            render: function RenderLabel(_label: any, key: APIKeyTableRow) {
                return (
                    <Link subtle className="text-left font-semibold truncate" onClick={() => onEdit(key.id)}>
                        {String(key.label)}
                    </Link>
                )
            },
        },
        {
            title: 'Secret key',
            dataIndex: 'mask_value',
            key: 'mask_value',
            render: (_: any, key: APIKeyTableRow) =>
                key.mask_value ? (
                    <span className="font-mono">{key.mask_value}</span>
                ) : (
                    <Tooltip title="This key was created before the introduction of previews">
                        <span className="inline-flex items-center gap-1">
                            <span>No preview</span>
                        </span>
                    </Tooltip>
                ),
        },
        {
            title: 'Scopes',
            key: 'scopes',
            dataIndex: 'scopes',
            render: function RenderScopes(_: any, key: APIKeyTableRow) {
                return <TagList tags={key.scopes} onMoreClick={() => onEdit(key.id)} />
            },
        },
        ...(showCreatedBy
            ? [
                  {
                      title: 'Created by',
                      key: 'created_by',
                      dataIndex: 'created_by',
                      render: (_: any, key: APIKeyTableRow) =>
                          key.created_by ? `${key.created_by.first_name || key.created_by.email}` : 'Unknown',
                  },
              ]
            : []),
        {
            title: 'Last used',
            dataIndex: 'last_used_at',
            key: 'lastUsedAt',
            render: (_: any, key: APIKeyTableRow) => (
                <Tooltip title={detailedTime(key.last_used_at)}>
                    {humanFriendlyDetailedTime(key.last_used_at, 'MMMM DD, YYYY', 'h A')}
                </Tooltip>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'createdAt',
            render: (_: any, key: APIKeyTableRow) => (
                <Tooltip title={detailedTime(key.created_at)}>{humanFriendlyDetailedTime(key.created_at)}</Tooltip>
            ),
        },
        {
            title: 'Last rolled',
            dataIndex: 'last_rolled_at',
            key: 'lastRolledAt',
            render: (_: any, key: APIKeyTableRow) => (
                <Tooltip title={detailedTime(key.last_rolled_at)}>
                    {humanFriendlyDetailedTime(key.last_rolled_at, 'MMMM DD, YYYY', 'h A')}
                </Tooltip>
            ),
        },
        ...(showActions
            ? [
                  {
                      title: '',
                      key: 'actions',
                      align: 'right',
                      width: 0,
                      render: (_: any, key: APIKeyTableRow) => (
                          <LemonMenu
                              items={[
                                  {
                                      label: 'Edit',
                                      onClick: () => onEdit(key.id),
                                  },
                                  {
                                      label: 'Roll',
                                      onClick: () => {
                                          LemonDialog.open({
                                              title: `Roll key "${key.label}"?`,
                                              description:
                                                  'This will generate a new key. The old key will immediately stop working.',
                                              primaryButton: {
                                                  status: 'danger',
                                                  children: 'Roll',
                                                  onClick: () => onRoll(key.id),
                                              },
                                              secondaryButton: {
                                                  children: 'Cancel',
                                              },
                                          })
                                      },
                                  },
                                  {
                                      label: 'Delete',
                                      status: 'danger',
                                      onClick: () => {
                                          LemonDialog.open({
                                              title: `Permanently delete key "${key.label}"?`,
                                              description: 'This action cannot be undone.',
                                              primaryButton: {
                                                  status: 'danger',
                                                  children: 'Delete',
                                                  onClick: () => onDelete(key.id),
                                              },
                                          })
                                      },
                                  },
                              ]}
                          >
                              <LemonButton size="small" icon={<IconEllipsis />} />
                          </LemonMenu>
                      ),
                  },
              ]
            : []),
    ]

    return (
        <LemonTable
            dataSource={keys}
            loading={loading}
            loadingSkeletonRows={3}
            className="mt-4"
            nouns={[noun, `${noun}s`]}
            columns={columns}
        />
    )
}
