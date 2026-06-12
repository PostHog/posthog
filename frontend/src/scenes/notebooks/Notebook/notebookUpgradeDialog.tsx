import { NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { membersLogic } from 'scenes/organization/membersLogic'

import { CommentType } from '~/types'

import {
    buildMarkdownNotebookContent,
    convertNotebookContentToMarkdown,
    notebookContentHasCommentMarks,
} from './markdownNotebookV2'

type OpenUpgradeToMarkdownNotebookDialogProps = {
    content: JSONContent | null | undefined
    /** The notebook's discussion comments — inline threads are embedded into the markdown. */
    comments?: CommentType[] | null
    setLocalContent: (jsonContent: JSONContent) => void
}

/**
 * Groups a notebook's range-anchored comments (item_context.type === 'mark') into reply
 * threads keyed by their v1 comment mark id, so the converter can emit a matching
 * `<Comment ref="markId" replies={…} />` thread next to each `<ref>` highlight.
 */
export function buildCommentRepliesByMarkId(
    comments: CommentType[] | null | undefined
): Record<string, NotebookPropValue[]> {
    const repliesByMarkId: Record<string, NotebookPropValue[]> = {}
    const toReply = (comment: CommentType): NotebookPropValue => {
        const author = comment.created_by?.first_name || comment.created_by?.email
        return {
            id: comment.id,
            text: comment.content ?? '',
            ...(author ? { author } : {}),
            ...(comment.created_by ? { authorId: comment.created_by.id } : {}),
            at: comment.created_at,
        }
    }

    for (const comment of comments ?? []) {
        if (
            comment.deleted ||
            comment.source_comment ||
            comment.item_context?.type !== 'mark' ||
            typeof comment.item_context?.id !== 'string'
        ) {
            continue
        }

        const thread = [
            comment,
            ...(comments ?? []).filter(
                (candidate) =>
                    candidate.source_comment === comment.id && !candidate.deleted && !candidate.item_context?.is_emoji
            ),
        ].sort((left, right) => left.created_at.localeCompare(right.created_at))

        repliesByMarkId[comment.item_context.id] = thread.map(toReply)
    }

    return repliesByMarkId
}

function getMentionLabel(memberId: number): string | null {
    const member = membersLogic
        .findMounted()
        ?.values.meFirstMembers?.find((candidate) => candidate.user.id === memberId)
    if (!member) {
        return null
    }
    return `@${member.user.first_name || member.user.email}`
}

export function openUpgradeToMarkdownNotebookDialog({
    content,
    comments,
    setLocalContent,
}: OpenUpgradeToMarkdownNotebookDialogProps): void {
    LemonDialog.open({
        title: 'Convert this notebook to Markdown notebooks?',
        content: (
            <div className="text-sm text-secondary">
                <p>
                    This conversion only works one way. Once upgraded, this notebook cannot be converted back to the old
                    editor.
                </p>
                {notebookContentHasCommentMarks(content) && (
                    <p className="mt-2">
                        Inline comments come along: each becomes a comment thread anchored to the same highlighted text.
                    </p>
                )}
                <p className="mt-2">Make sure you want to continue before converting it.</p>
            </div>
        ),
        primaryButton: {
            children: 'Convert to Markdown notebooks',
            type: 'primary',
            onClick: () =>
                setLocalContent(
                    buildMarkdownNotebookContent(
                        convertNotebookContentToMarkdown(content, {
                            commentRepliesByMarkId: buildCommentRepliesByMarkId(comments),
                            getMentionLabel,
                        })
                    )
                ),
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}
