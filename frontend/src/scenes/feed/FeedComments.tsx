import { useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

interface Comment {
    id: string
    content: string
    created_at: string
    created_by: {
        id: number
        first_name: string
        email: string
    }
    source_comment: string | null
}

interface FeedCommentsProps {
    scope: string
    itemId: string
}

export function FeedComments({ scope, itemId }: FeedCommentsProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const [comments, setComments] = useState<Comment[]>([])
    const [loading, setLoading] = useState(true)
    const [newComment, setNewComment] = useState('')
    const [submitting, setSubmitting] = useState(false)

    const loadComments = useCallback(async (): Promise<void> => {
        try {
            setLoading(true)
            const response = await fetch(
                `/api/projects/${currentTeamId}/comments/?scope=${scope}&item_id=${itemId}&exclude_emoji_reactions=true`,
                {
                    credentials: 'include',
                }
            )
            const data = await response.json()
            setComments(data.results || [])
        } catch (error) {
            console.error('Failed to load comments:', error)
        } finally {
            setLoading(false)
        }
    }, [currentTeamId, scope, itemId])

    useEffect(() => {
        loadComments()
    }, [loadComments])

    const handleSubmit = async (): Promise<void> => {
        if (!newComment.trim()) {
            return
        }

        try {
            setSubmitting(true)
            const response = await fetch(`/api/projects/${currentTeamId}/comments/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    content: newComment,
                    scope,
                    item_id: itemId,
                }),
            })

            if (response.ok) {
                setNewComment('')
                await loadComments()
            }
        } catch (error) {
            console.error('Failed to post comment:', error)
        } finally {
            setSubmitting(false)
        }
    }

    if (loading) {
        return (
            <div className="flex justify-center py-4">
                <Spinner />
            </div>
        )
    }

    return (
        <div className="space-y-3">
            {/* Existing Comments */}
            {comments.length > 0 && (
                <div className="space-y-3">
                    {comments.map((comment) => (
                        <div key={comment.id} className="flex gap-2">
                            <div className="flex-shrink-0">
                                <ProfilePicture
                                    size="sm"
                                    name={comment.created_by?.first_name || comment.created_by?.email}
                                />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="bg-accent-light rounded-lg p-3">
                                    <div className="font-semibold text-sm">
                                        {comment.created_by?.first_name || comment.created_by?.email}
                                    </div>
                                    <div className="text-sm mt-1">{comment.content}</div>
                                </div>
                                <div className="text-xs text-muted mt-1 ml-3">
                                    <TZLabel time={comment.created_at} />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* New Comment Input */}
            <div className="flex gap-2">
                <div className="flex-shrink-0">
                    <ProfilePicture size="sm" name={user?.first_name || user?.email} />
                </div>
                <div className="flex-1 min-w-0">
                    <LemonTextArea
                        placeholder="Write a comment..."
                        value={newComment}
                        onChange={(value) => setNewComment(value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                handleSubmit()
                            }
                        }}
                        className="w-full"
                        minRows={1}
                    />
                    <div className="flex justify-end gap-2 mt-2">
                        {newComment.trim() && (
                            <>
                                <LemonButton size="small" type="secondary" onClick={() => setNewComment('')}>
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    onClick={handleSubmit}
                                    loading={submitting}
                                    disabledReason={!newComment.trim() ? 'Enter a comment' : undefined}
                                >
                                    Post
                                </LemonButton>
                            </>
                        )}
                    </div>
                </div>
            </div>

            {comments.length === 0 && !loading && (
                <div className="text-center text-muted text-sm py-2">No comments yet. Be the first to comment!</div>
            )}
        </div>
    )
}
