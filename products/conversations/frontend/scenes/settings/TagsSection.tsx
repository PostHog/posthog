import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type { TagUsageApi } from '~/generated/core/api.schemas'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { openDeleteTagDialog, openMergeTagDialog, openRenameTagDialog } from './supportTagDialogs'
import { objectKindLabel, otherObjectCount, supportTagsLogic, ticketCount } from './supportTagsLogic'

function OtherUsage({ tag }: { tag: TagUsageApi }): JSX.Element {
    const others = otherObjectCount(tag)
    if (others === 0) {
        return <span className="text-muted-alt">None</span>
    }
    const breakdown = Object.entries(tag.counts_by_type)
        .filter(([kind]) => kind !== 'ticket')
        .map(([kind, count]) => objectKindLabel(kind, count))
        .join(', ')
    return (
        <Tooltip title={`Also on ${breakdown}. A rename, merge, or delete applies to those too.`}>
            <span className="border-b border-dashed cursor-help">{others}</span>
        </Tooltip>
    )
}

export function TagsSection(): JSX.Element {
    const { tags, tagsLoading, search } = useValues(supportTagsLogic)
    const { setSearch, renameTag, deleteTag, mergeTag } = useActions(supportTagsLogic)

    return (
        <SceneSection
            title="Tags"
            description="Rename, merge, or delete the tags on your support tickets. Tags are shared across the project, so a change here also applies anywhere else the tag is used."
        >
            <LemonInput
                type="search"
                placeholder="Search tags"
                value={search}
                onChange={setSearch}
                className="max-w-80"
                data-attr="support-tags-search"
            />
            <LemonTable
                dataSource={tags ?? []}
                loading={tagsLoading && tags === null}
                rowKey="id"
                pagination={{ pageSize: 20 }}
                emptyState={
                    search ? 'No tags match your search.' : 'No tags yet. Add one from a ticket and it shows up here.'
                }
                columns={[
                    {
                        title: 'Tag',
                        key: 'name',
                        render: (_, tag) => <LemonTag>{tag.name}</LemonTag>,
                    },
                    {
                        title: 'Tickets',
                        key: 'tickets',
                        align: 'right',
                        render: (_, tag) => ticketCount(tag),
                    },
                    {
                        title: 'Elsewhere',
                        key: 'elsewhere',
                        align: 'right',
                        render: (_, tag) => <OtherUsage tag={tag} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, tag) => (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Rename',
                                        onClick: () => openRenameTagDialog(tag, (name) => renameTag({ tag, name })),
                                    },
                                    {
                                        label: 'Merge into',
                                        disabledReason:
                                            (tags ?? []).length < 2 ? 'There is no other tag to merge into' : undefined,
                                        onClick: () =>
                                            openMergeTagDialog(
                                                tag,
                                                (tags ?? []).filter((other) => other.id !== tag.id),
                                                (intoId) => mergeTag({ tag, intoId })
                                            ),
                                    },
                                    {
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => openDeleteTagDialog(tag, () => deleteTag({ tag })),
                                    },
                                ]}
                            >
                                <LemonButton
                                    icon={<IconEllipsis />}
                                    size="small"
                                    loading={tagsLoading}
                                    data-attr="support-tag-actions"
                                />
                            </LemonMenu>
                        ),
                    },
                ]}
            />
        </SceneSection>
    )
}
