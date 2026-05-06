import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { MicrophoneHog } from 'lib/components/hedgehogs'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { getText } from 'scenes/comments/Comment'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { CommentType } from '~/types'

import { SCOPE_OPTIONS, commentsLogic, openURLFor } from './commentsLogic'

const KIND_OPTIONS = [
    { value: 'any', label: 'Any' },
    { value: 'comment', label: 'Comments' },
    { value: 'task', label: 'Tasks' },
] as const

const COMPLETED_OPTIONS = [
    { value: 'any', label: 'Any' },
    { value: 'open', label: 'Open' },
    { value: 'completed', label: 'Completed' },
] as const

export function Comments(): JSX.Element {
    const { user } = useValues(userLogic)

    const {
        comments,
        shouldShowEmptyState,
        commentsLoading,
        scope,
        filterCreatedBy,
        searchText,
        kind,
        completedFilter,
    } = useValues(commentsLogic)

    const {
        setScope,
        setFilterCreatedBy,
        setSearchText,
        setKind,
        setCompletedFilter,
        deleteComment,
        completeComment,
        reopenComment,
        loadComments,
    } = useActions(commentsLogic)

    useEffect(() => {
        loadComments()
    }, [loadComments])

    const columns: LemonTableColumns<CommentType> = [
        {
            title: 'Comment',
            key: 'content',
            width: '45%',
            render: function RenderComment(_, comment: CommentType): JSX.Element {
                const isCompleted = !!comment.completed_at
                const completionTooltip = isCompleted
                    ? `Completed by ${comment.completed_by?.first_name ?? 'Unknown user'}`
                    : 'Mark as complete'
                return (
                    <div className="flex items-center gap-2">
                        {comment.is_task ? (
                            <Tooltip title={completionTooltip}>
                                <LemonCheckbox
                                    checked={isCompleted}
                                    onChange={() => (isCompleted ? reopenComment(comment) : completeComment(comment))}
                                    data-attr="comment-task-checkbox"
                                />
                            </Tooltip>
                        ) : null}
                        <div
                            className={clsx(
                                'whitespace-pre-wrap break-words max-h-64 overflow-y-auto min-w-0 flex-1',
                                isCompleted && 'line-through text-secondary'
                            )}
                            data-attr="comment-scene-comment-title-rendered-content"
                        >
                            {getText(comment)}
                        </div>
                    </div>
                )
            },
        },
        {
            title: `Timestamp`,
            dataIndex: 'created_at',
            render: function RenderCreatedAt(_, comment: CommentType): JSX.Element {
                return <TZLabel time={dayjs(comment.created_at)} />
            },
            sorter: (a, b) => dayjs(a.created_at).diff(dayjs(b.created_at)),
        },
        {
            title: 'Kind',
            key: 'kind',
            render: function RenderKind(_, comment: CommentType): JSX.Element {
                return <span>{comment.is_task ? 'Task' : 'Comment'}</span>
            },
        },
        {
            title: 'Scope',
            key: 'scope',
            render: function RenderScope(_, comment: CommentType): JSX.Element {
                return <LemonTag className="uppercase">{comment.scope}</LemonTag>
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: function RenderCreatedBy(_: any, comment: CommentType) {
                return (
                    <div className="flex flex-row items-center">
                        <ProfilePicture user={comment.created_by} showName size="md" type="person" />
                    </div>
                )
            },
            sorter: (a, b) =>
                (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                    b.created_by?.first_name || b.created_by?.email || ''
                ),
        },
        {
            key: 'actions',
            width: 0,
            render: function RenderActions(_, comment: CommentType): JSX.Element {
                const canEdit = user?.uuid === comment.created_by?.uuid
                return (
                    <div className="flex">
                        <>
                            <LemonButton
                                icon={<IconTrash />}
                                size="small"
                                status="danger"
                                onClick={() => deleteComment(comment.id)}
                                disabledReason={canEdit ? undefined : 'You can only delete your own comments'}
                                data-attr="comment-management-scene-delete"
                            />
                            <LemonButton
                                icon={<IconOpenInApp />}
                                size="small"
                                to={openURLFor(comment) || ''}
                                disabledReason={
                                    openURLFor(comment)
                                        ? undefined
                                        : 'We are not able to link to this comment type 🙈tell us you want to be able to!'
                                }
                                data-attr="comment-management-scene-open"
                            />
                        </>
                    </div>
                )
            },
        },
    ]

    return (
        <SceneContent data-attr="comments-management-scene">
            <SceneTitleSection
                name={sceneConfigurations[Scene.Comments].name}
                description={sceneConfigurations[Scene.Comments].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Comments].iconType || 'default_icon_type',
                }}
            />
            <div className="flex flex-row gap-4 justify-between">
                <div className="flex flex-row items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search comments..."
                        value={searchText}
                        onChange={setSearchText}
                        size="small"
                    />
                </div>

                <div>
                    <div className="flex flex-row items-center gap-4 flex-wrap">
                        <div className="flex flex-row items-center gap-2">
                            <div>Kind:</div>
                            <LemonSelect options={[...KIND_OPTIONS]} value={kind} onSelect={setKind} size="small" />
                        </div>

                        {kind === 'task' ? (
                            <div className="flex flex-row items-center gap-2">
                                <div>Status:</div>
                                <LemonSelect
                                    options={[...COMPLETED_OPTIONS]}
                                    value={completedFilter}
                                    onSelect={setCompletedFilter}
                                    size="small"
                                />
                            </div>
                        ) : null}

                        <div className="flex flex-row items-center gap-2">
                            <div>Scope:</div>
                            <LemonSelect options={SCOPE_OPTIONS} value={scope} onSelect={setScope} size="small" />
                        </div>

                        <div className="flex items-center gap-2">
                            <span>Created by:</span>
                            <MemberSelect
                                value={filterCreatedBy}
                                onChange={(user) => {
                                    setFilterCreatedBy(user?.uuid ?? null)
                                }}
                            />
                        </div>
                    </div>
                </div>
            </div>

            <div data-attr="comments-content">
                <div className="mt-4">
                    <ProductIntroduction
                        productName="Comments"
                        productKey={ProductKey.COMMENTS}
                        thingName="comment"
                        description="Comments allow you to provide context and discussions on various elements in PostHog."
                        isEmpty={shouldShowEmptyState}
                        customHog={MicrophoneHog}
                    />
                </div>
                {!shouldShowEmptyState && (
                    <LemonTable
                        data-attr="comments-table"
                        rowKey="id"
                        dataSource={comments}
                        columns={columns}
                        defaultSorting={{
                            columnKey: 'created_at',
                            order: -1,
                        }}
                        noSortingCancellation
                        loading={commentsLoading}
                        emptyState="No comments found"
                    />
                )}
            </div>
        </SceneContent>
    )
}
