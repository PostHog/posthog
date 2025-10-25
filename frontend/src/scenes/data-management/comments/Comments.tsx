import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { MicrophoneHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { CommentType, ProductKey } from '~/types'

import { SCOPE_OPTIONS, commentsLogic, openURLFor } from './commentsLogic'

export function Comments(): JSX.Element {
    const { user } = useValues(userLogic)

    const { comments, shouldShowEmptyState, commentsLoading, scope, filterCreatedBy, searchText } =
        useValues(commentsLogic)

    const { setScope, setFilterCreatedBy, setSearchText, deleteComment, loadComments } = useActions(commentsLogic)

    useEffect(() => {
        loadComments()
    }, [loadComments])

    const columns: LemonTableColumns<CommentType> = [
        {
            title: 'Comment',
            key: 'content',
            width: '30%',
            render: function RenderComment(_, comment: CommentType): JSX.Element {
                let renderedContent = <>{comment.content ?? ''}</>
                if ((comment.content || '').trim().length > 50) {
                    renderedContent = (
                        <Tooltip
                            title={
                                <div
                                    className="whitespace-pre-wrap break-words"
                                    data-attr="comment-scene-comment-title-rendered-content"
                                >
                                    {comment.content ?? ''}
                                </div>
                            }
                        >
                            {(comment.content ?? '').slice(0, 47) + '...'}
                        </Tooltip>
                    )
                }
                return <div className="font-semibold">{renderedContent}</div>
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
            <SceneDivider />
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
