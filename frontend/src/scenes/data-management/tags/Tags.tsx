import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconMerge, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Link } from 'lib/lemon-ui/Link'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { TagItemType, TagType } from '~/types'

import { tagsLogic } from './tagsLogic'

/** Map each backend `RELATED_OBJECTS` entry to the URL of its list/detail scene. */
const TAG_ITEM_URL: Record<string, (id: string) => string> = {
    dashboard: (id) => urls.dashboard(id),
    insight: (id) => urls.insightView(id as any),
    event_definition: (id) => urls.eventDefinition(id),
    property_definition: (id) => urls.propertyDefinition(id),
    action: (id) => urls.action(id),
    feature_flag: (id) => urls.featureFlag(id),
    experiment_saved_metric: () => urls.experimentsSharedMetrics(),
    experiment: (id) => urls.experiment(id),
    cohort: (id) => urls.cohort(id),
    notebook: (id) => urls.notebook(id),
    survey: (id) => urls.survey(id),
    session_recording_playlist: (id) => urls.replayPlaylist(id),
    data_warehouse_saved_query: () => urls.sqlEditor(),
    hog_function: (id) => urls.hogFunction(id),
    batch_export: (id) => urls.batchExport(id),
    error_tracking_issue: (id) => urls.errorTrackingIssue(id),
    ticket: (id) => urls.supportTicketDetail(id),
}

const ENTITY_TYPE_LABEL: Record<string, string> = {
    dashboard: 'Dashboard',
    insight: 'Insight',
    event_definition: 'Event definition',
    property_definition: 'Property definition',
    action: 'Action',
    feature_flag: 'Feature flag',
    experiment_saved_metric: 'Shared metric',
    experiment: 'Experiment',
    cohort: 'Cohort',
    notebook: 'Notebook',
    survey: 'Survey',
    session_recording_playlist: 'Playlist',
    data_warehouse_saved_query: 'SQL view',
    hog_function: 'Function',
    batch_export: 'Batch export',
    error_tracking_issue: 'Error tracking issue',
    ticket: 'Support ticket',
}

export function Tags(): JSX.Element {
    const {
        tags,
        tagsLoading,
        filteredTags,
        search,
        mergeDialogSource,
        itemsDrawerTag,
        itemsForTag,
        itemsForTagLoading,
    } = useValues(tagsLogic)
    const {
        setSearch,
        createTag,
        renameTag,
        deleteTag,
        openMergeDialog,
        closeMergeDialog,
        mergeTag,
        openItemsDrawer,
        closeItemsDrawer,
    } = useActions(tagsLogic)

    const [newTagName, setNewTagName] = useState('')

    const columns: LemonTableColumns<TagType> = [
        {
            title: 'Tag',
            key: 'name',
            dataIndex: 'name',
            render: (_, tag) => <ObjectTags tags={[tag.name]} staticOnly />,
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Used on',
            key: 'usage_count',
            dataIndex: 'usage_count',
            render: (count, tag) => (
                <LemonButton size="small" type="tertiary" onClick={() => openItemsDrawer(tag)}>
                    {count} {count === 1 ? 'entity' : 'entities'}
                </LemonButton>
            ),
            sorter: (a, b) => a.usage_count - b.usage_count,
        },
        {
            title: 'Actions',
            key: 'actions',
            align: 'right',
            width: 0,
            render: (_, tag) => (
                <div className="flex justify-end gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Rename tag"
                        onClick={() =>
                            LemonDialog.openForm({
                                title: `Rename tag "${tag.name}"`,
                                initialValues: { name: tag.name },
                                content: (
                                    <LemonInput
                                        name="name"
                                        placeholder="new-tag-name"
                                        autoFocus
                                        autoComplete="off"
                                    />
                                ),
                                errors: {
                                    name: (name) => (!name ? 'Name is required' : undefined),
                                },
                                onSubmit: ({ name }) => renameTag({ id: tag.id, name }),
                            })
                        }
                    />
                    <LemonButton
                        size="small"
                        icon={<IconMerge />}
                        tooltip="Merge into another tag"
                        onClick={() => openMergeDialog(tag)}
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete tag everywhere"
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete "${tag.name}" from every entity?`,
                                description: `This removes the tag from all ${tag.usage_count} entities in this project. This cannot be undone.`,
                                primaryButton: {
                                    status: 'danger',
                                    children: 'Delete tag',
                                    onClick: () => deleteTag(tag.id),
                                },
                            })
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection name="Tags" description="Manage tags used across dashboards, insights, notebooks, cohorts, feature flags, and more." />

            <div className="flex gap-2 items-center">
                <LemonInput
                    placeholder="Search tags…"
                    value={search}
                    onChange={setSearch}
                    size="small"
                    className="max-w-[360px]"
                />
                <div className="flex-1" />
                <LemonInput
                    placeholder="new-tag"
                    value={newTagName}
                    onChange={setNewTagName}
                    size="small"
                    onPressEnter={() => {
                        if (newTagName.trim()) {
                            createTag(newTagName)
                            setNewTagName('')
                        }
                    }}
                />
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => {
                        if (newTagName.trim()) {
                            createTag(newTagName)
                            setNewTagName('')
                        }
                    }}
                    disabledReason={!newTagName.trim() ? 'Enter a name first' : undefined}
                >
                    New tag
                </LemonButton>
            </div>

            <LemonTable
                columns={columns}
                dataSource={filteredTags}
                loading={tagsLoading}
                rowKey="id"
                emptyState="No tags yet. Create one on the right, or tag any entity (dashboard, insight, notebook, cohort, …) to see it listed here."
            />

            {mergeDialogSource ? (
                <MergeDialog
                    source={mergeDialogSource}
                    targets={tags.filter((tag) => tag.id !== mergeDialogSource.id)}
                    onClose={closeMergeDialog}
                    onSubmit={(targetId) => {
                        mergeTag({ sourceId: mergeDialogSource.id, targetId })
                        closeMergeDialog()
                    }}
                />
            ) : null}

            {itemsDrawerTag ? (
                <LemonModal
                    isOpen
                    onClose={closeItemsDrawer}
                    title={`Entities tagged "${itemsDrawerTag.name}"`}
                    description={`${itemsDrawerTag.usage_count} ${
                        itemsDrawerTag.usage_count === 1 ? 'entity' : 'entities'
                    }`}
                    width={640}
                >
                    <TagItemsList items={itemsForTag} loading={itemsForTagLoading} />
                </LemonModal>
            ) : null}
        </SceneContent>
    )
}

function MergeDialog({
    source,
    targets,
    onClose,
    onSubmit,
}: {
    source: TagType
    targets: TagType[]
    onClose: () => void
    onSubmit: (targetId: string) => void
}): JSX.Element {
    const [targetId, setTargetId] = useState<string | null>(null)
    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={`Merge "${source.name}" into another tag`}
            description={`Every entity currently tagged with "${source.name}" will instead be tagged with the target. "${source.name}" will then be deleted.`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={targetId ? undefined : 'Pick a target tag'}
                        onClick={() => targetId && onSubmit(targetId)}
                    >
                        Merge
                    </LemonButton>
                </>
            }
        >
            <LemonSelect
                fullWidth
                value={targetId}
                onChange={setTargetId}
                placeholder="Select a target tag"
                options={targets.map((tag) => ({
                    value: tag.id,
                    label: `${tag.name} (used on ${tag.usage_count})`,
                }))}
            />
        </LemonModal>
    )
}

function TagItemsList({ items, loading }: { items: TagItemType[]; loading: boolean }): JSX.Element {
    if (loading && items.length === 0) {
        return <div className="p-4">Loading…</div>
    }
    if (items.length === 0) {
        return <div className="p-4 text-secondary">No entities are tagged with this tag yet.</div>
    }
    const grouped = items.reduce<Record<string, TagItemType[]>>((acc, item) => {
        ;(acc[item.type] ||= []).push(item)
        return acc
    }, {})
    return (
        <div className="flex flex-col gap-4">
            {Object.entries(grouped).map(([type, groupItems]) => (
                <div key={type}>
                    <h4 className="text-secondary mb-1">{ENTITY_TYPE_LABEL[type] ?? type}</h4>
                    <ul className="list-disc pl-5">
                        {groupItems.map((item) => {
                            const hrefBuilder = TAG_ITEM_URL[item.type]
                            const href = hrefBuilder?.(item.id)
                            return (
                                <li key={`${item.type}:${item.id}`}>
                                    {href ? (
                                        <Link to={href}>{item.name ?? item.id}</Link>
                                    ) : (
                                        <span>{item.name ?? item.id}</span>
                                    )}
                                </li>
                            )
                        })}
                    </ul>
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: Tags,
    logic: tagsLogic,
}
