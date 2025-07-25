import { LemonSelect } from '@posthog/lemon-ui'
import { MicrophoneHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ProductKey } from '~/types'

export function Comments(): JSX.Element {
    // const { currentTeam, timezone } = useValues(teamLogic)
    //
    // const { currentOrganization } = useValues(organizationLogic)

    // const columns: LemonTableColumns<CommentType> = [
    //     {
    //         title: 'Comment',
    //         key: 'comment',
    //         width: '30%',
    //         render: function RenderComment(_, comment: CommentType): JSX.Element {
    //             let renderedContent = <>{comment.content ?? ''}</>
    //             if ((comment.content || '').trim().length > 30) {
    //                 renderedContent = (
    //                     <Tooltip
    //                         title={
    //                             <TextContent
    //                                 text={comment.content ?? ''}
    //                                 data-attr="comment-scene-comment-title-rendered-content"
    //                             />
    //                         }
    //                     >
    //                         {(comment.content ?? '').slice(0, 27) + '...'}
    //                     </Tooltip>
    //                 )
    //             }
    //             return (
    //                 <div className="font-semibold">
    //                     <Link subtle to={urls.comment(comment.id)}>
    //                         {renderedContent}
    //                     </Link>
    //                 </div>
    //             )
    //         },
    //     },
    //     {
    //         title: `Date and time (${shortTimeZone(timezone)})`,
    //         dataIndex: 'created_at',
    //         render: function RenderDateMarker(_, comment: CommentType): string {
    //             return comment.created_at
    //         },
    //         sorter: (a, b) => dayjs(a.created_at)?.diff(dayjs(b.created_at)) || 1,
    //     },
    //     {
    //         title: 'Scope',
    //         key: 'scope',
    //         render: function RenderType(_, comment: CommentType): JSX.Element {
    //             return <>{comment.scope}</>
    //         },
    //     },
    //     {
    //         title: 'Created by',
    //         dataIndex: 'created_by',
    //         render: function Render(_: any, item) {
    //             const { created_by } = item
    //             return (
    //                 <div className="flex flex-row items-center">
    //                     <ProfilePicture
    //                         user={created_by}
    //                         showName
    //                         size="md"
    //                         type='person'
    //                     />
    //                 </div>
    //             )
    //         },
    //         sorter: (a, b) =>
    //             (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
    //                 b.created_by?.first_name || b.created_by?.email || ''
    //             ),
    //     },
    //     createdAtColumn() as LemonTableColumn<CommentType, keyof CommentType | undefined>,
    //     {
    //         key: 'actions',
    //         width: 0,
    //         render: function RenderActions(_, comment): JSX.Element {
    //             return <LemonButton icon={<IconPencil />} size="small" to={urls.comment(comment.id)} />
    //         },
    //     },
    // ]

    return (
        <>
            <div className="flex flex-row items-center gap-2 justify-between">
                <div>
                    Annotations allow you to mark when certain changes happened so you can easily see how they impacted
                    your metrics.
                </div>
                <div className="flex flex-row items-center gap-2">
                    <div>Scope: </div>
                    <LemonSelect options={[]} value={undefined} onSelect={() => {}} />
                </div>
            </div>
            <div data-attr="annotations-content">
                <div className="mt-4">
                    <ProductIntroduction
                        productName="Annotations"
                        productKey={ProductKey.COMMENTS}
                        thingName="annotation"
                        description="Annotations allow you to mark when certain changes happened so you can easily see how they impacted your metrics."
                        docsURL="https://posthog.com/docs/data/comments"
                        action={() => {}}
                        isEmpty={false}
                        customHog={MicrophoneHog}
                    />
                </div>
                {/*{!shouldShowEmptyState && (*/}
                {/*    <>*/}
                {/*        <LemonTable*/}
                {/*            data-attr="annotations-table"*/}
                {/*            rowKey="id"*/}
                {/*            dataSource={filteredAnnotations}*/}
                {/*            columns={columns}*/}
                {/*            defaultSorting={{*/}
                {/*                columnKey: 'date_marker',*/}
                {/*                order: -1,*/}
                {/*            }}*/}
                {/*            noSortingCancellation*/}
                {/*            loading={annotationsLoading}*/}
                {/*            emptyState="No annotations yet"*/}
                {/*        />*/}
                {/*        {next && (*/}
                {/*            <div className="flex justify-center mt-6">*/}
                {/*                <LemonButton*/}
                {/*                    type="primary"*/}
                {/*                    loading={loadingNext}*/}
                {/*                    onClick={(): void => {*/}
                {/*                        loadAnnotationsNext()*/}
                {/*                    }}*/}
                {/*                >*/}
                {/*                    Load more annotations*/}
                {/*                </LemonButton>*/}
                {/*            </div>*/}
                {/*        )}*/}
                {/*    </>*/}
                {/*)}*/}
            </div>
        </>
    )
}
