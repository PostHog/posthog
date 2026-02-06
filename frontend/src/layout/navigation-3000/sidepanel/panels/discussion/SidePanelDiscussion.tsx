import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconChat } from '@posthog/icons'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { WarningHog } from 'lib/components/hedgehogs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'
import { CommentsLogicProps, commentsLogic } from 'scenes/comments/commentsLogic'

import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { sidePanelDiscussionLogic } from './sidePanelDiscussionLogic'

export const SidePanelDiscussionIcon = (props: { className?: string }): JSX.Element => {
    const { commentCount } = useValues(sidePanelDiscussionLogic)

    return (
        <IconWithCount count={commentCount} {...props}>
            <IconChat />
        </IconWithCount>
    )
}

export const SidePanelDiscussion = (): JSX.Element => {
    const { commentsLogicProps } = useValues(sidePanelDiscussionLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')
    const { scope, item_id } = commentsLogicProps ?? {}

    return (
        <div className="flex flex-col overflow-hidden flex-1">
            {!isRemovingSidePanelFlag ? (
                <SidePanelPaneHeader
                    title={
                        <div className="flex deprecated-space-x-2">
                            <span>
                                Discussion{' '}
                                {scope ? (
                                    <span className="font-normal text-secondary">
                                        about {item_id ? 'this' : ''} {humanizeScope(scope, !!item_id)}
                                    </span>
                                ) : null}
                            </span>
                        </div>
                    }
                />
            ) : null}

            <SidePanelContentContainer flagOffClassName="contents">
                {commentsLogicProps && commentsLogicProps.disabled && isRemovingSidePanelFlag ? (
                    <SidePanelPaneHeader
                        title={
                            <div className="flex deprecated-space-x-2">
                                <span>
                                    Discussion{' '}
                                    {scope ? (
                                        <span className="font-normal text-secondary">
                                            about {item_id ? 'this' : ''} {humanizeScope(scope, !!item_id)}
                                        </span>
                                    ) : null}
                                </span>
                            </div>
                        }
                    />
                ) : null}
                {commentsLogicProps && !commentsLogicProps.disabled ? (
                    <DiscussionContent logicProps={commentsLogicProps}>
                        {isRemovingSidePanelFlag ? (
                            <SidePanelPaneHeader
                                title={
                                    <div className="flex deprecated-space-x-2">
                                        <span>
                                            Discussion{' '}
                                            {scope ? (
                                                <span className="font-normal text-secondary">
                                                    about {item_id ? 'this' : ''} {humanizeScope(scope, !!item_id)}
                                                </span>
                                            ) : null}
                                        </span>
                                    </div>
                                }
                            />
                        ) : null}
                    </DiscussionContent>
                ) : (
                    <div className="mx-auto p-8 max-w-160 mt-8 deprecated-space-y-4">
                        <div className={cn('max-w-80 mx-auto', isRemovingSidePanelFlag && 'max-w-24')}>
                            <WarningHog className="w-full h-full" />
                        </div>
                        <h2>Discussions aren't supported here yet...</h2>
                        <p>
                            This a beta feature that is currently only available when viewing things like an Insight,
                            Dashboard or Notebook.
                        </p>
                    </div>
                )}
            </SidePanelContentContainer>
        </div>
    )
}

const DiscussionContent = ({
    logicProps,
    children,
}: {
    logicProps: CommentsLogicProps
    children?: React.ReactNode
}): JSX.Element => {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const { setReplyingComment } = useActions(commentsLogic(logicProps))
    const { setCommentsListRef } = useActions(sidePanelDiscussionLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    useEffect(() => {
        if (selectedTabOptions) {
            setReplyingComment(selectedTabOptions)
        }
    }, [selectedTabOptions]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <div
                className={cn('flex-1 overflow-y-auto p-2', isRemovingSidePanelFlag && 'p-0')}
                ref={setCommentsListRef}
            >
                {children}
                <CommentsList {...logicProps} />
            </div>

            <div className="border-t px-3 pb-3">
                <CommentComposer {...logicProps} />
            </div>
        </div>
    )
}
