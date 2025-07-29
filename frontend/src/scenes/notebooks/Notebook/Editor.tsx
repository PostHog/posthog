import ExtensionDocument from '@tiptap/extension-document'
import { FloatingMenu } from '@tiptap/extension-floating-menu'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import StarterKit from '@tiptap/starter-kit'
import { useActions, useMountedLogic, useValues } from 'kea'
import { sampleOne, uuid } from 'lib/utils'
import { useCallback, useMemo } from 'react'

import { NotebookMarkComment } from '../Marks/NotebookMarkComment'
import { NotebookMarkLink } from '../Marks/NotebookMarkLink'
import { NotebookNodeBacklink } from '../Nodes/NotebookNodeBacklink'
import { NotebookNodeCohort } from '../Nodes/NotebookNodeCohort'
import { NotebookNodeEarlyAccessFeature } from '../Nodes/NotebookNodeEarlyAccessFeature'
import { NotebookNodeEmbed } from '../Nodes/NotebookNodeEmbed'
import { NotebookNodeExperiment } from '../Nodes/NotebookNodeExperiment'
import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeFlagCodeExample } from '../Nodes/NotebookNodeFlagCodeExample'
import { NotebookNodeGroup } from '../Nodes/NotebookNodeGroup'
import { NotebookNodeImage } from '../Nodes/NotebookNodeImage'
import { NotebookNodeLatex } from '../Nodes/NotebookNodeLatex'
import { NotebookNodeMap } from '../Nodes/NotebookNodeMap'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'
import { NotebookNodePersonFeed } from '../Nodes/NotebookNodePersonFeed/NotebookNodePersonFeed'
import { NotebookNodePlaylist } from '../Nodes/NotebookNodePlaylist'
import { NotebookNodeProperties } from '../Nodes/NotebookNodeProperties'
import { NotebookNodeQuery } from '../Nodes/NotebookNodeQuery'
import { NotebookNodeRecording } from '../Nodes/NotebookNodeRecording'
import { NotebookNodeReplayTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { NotebookNodeSurvey } from '../Nodes/NotebookNodeSurvey'
import { FloatingSuggestions } from '../Suggestions/FloatingSuggestions'
import { insertionSuggestionsLogic } from '../Suggestions/insertionSuggestionsLogic'
import { InlineMenu } from './InlineMenu'
import { MentionsExtension } from '../../../lib/components/RichContentEditor/MentionsExtension'
import { notebookLogic } from './notebookLogic'
import { SlashCommandsExtension } from './SlashCommands'
import TableOfContents, { getHierarchicalIndexes } from '@tiptap/extension-table-of-contents'
import { RichContentNodeMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { createEditor } from 'lib/components/RichContentEditor/utils'
import { textContent } from '../utils'
import { RichContentNode, TTEditor } from 'lib/components/RichContentEditor/types'
import { RichContentEditor } from 'lib/components/RichContentEditor'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { NotebookEditor } from '../types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from '@posthog/icons'
import { DropAndPasteHandlerExtension } from './DropAndPasteHandlerExtension'

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Editor(): JSX.Element {
    const { shortId, mode } = useValues(notebookLogic)
    const { setEditor, onEditorUpdate, onEditorSelectionUpdate, setTableOfContents } = useActions(notebookLogic)
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')

    const { resetSuggestions, setPreviousNode } = useActions(insertionSuggestionsLogic)

    const headingPlaceholder = useMemo(() => sampleOne(PLACEHOLDER_TITLES), [shortId])

    const updatePreviousNode = useCallback(
        (editor: TTEditor) => {
            setPreviousNode(getNodeBeforeActiveNode(editor))
        },
        [setPreviousNode]
    )

    return (
        <RichContentEditor
            logicKey={`Notebook.${shortId}`}
            extensions={[
                mode === 'notebook' ? CustomDocument : ExtensionDocument,
                StarterKit.configure({
                    document: false,
                    gapcursor: false,
                }),
                TableOfContents.configure({
                    getIndex: getHierarchicalIndexes,
                    onUpdate(content) {
                        setTableOfContents(content)
                    },
                }),
                ExtensionPlaceholder.configure({
                    placeholder: ({ node }: { node: any }) => {
                        if (node.type.name === 'heading' && node.attrs.level === 1) {
                            return `Untitled - maybe.. "${headingPlaceholder}"`
                        }

                        if (node.type.name === 'heading') {
                            return `Heading ${node.attrs.level}`
                        }

                        return ''
                    },
                }),
                FloatingMenu.extend({
                    onSelectionUpdate(this) {
                        updatePreviousNode(this.editor)
                    },
                    onUpdate(this) {
                        updatePreviousNode(this.editor)
                        resetSuggestions()
                    },
                }),
                DropAndPasteHandlerExtension,
                TaskList,
                TaskItem.configure({ nested: true }),
                NotebookMarkLink,
                NotebookMarkComment,
                NotebookNodeLatex,
                NotebookNodeBacklink,
                NotebookNodeQuery,
                NotebookNodeRecording,
                NotebookNodeReplayTimestamp,
                NotebookNodePlaylist,
                NotebookNodePerson,
                NotebookNodeCohort,
                NotebookNodeGroup,
                NotebookNodeFlagCodeExample,
                NotebookNodeFlag,
                NotebookNodeExperiment,
                NotebookNodeEarlyAccessFeature,
                NotebookNodeSurvey,
                NotebookNodeImage,
                NotebookNodeProperties,
                RichContentNodeMention,
                NotebookNodeEmbed,
                SlashCommandsExtension,
                MentionsExtension,
                NotebookNodePersonFeed,
                NotebookNodeMap,
            ]}
            className="NotebookEditor flex flex-col flex-1"
            onUpdate={onEditorUpdate}
            onSelectionUpdate={onEditorSelectionUpdate}
            onCreate={(editor) => {
                // NOTE: This could be the wrong way of passing state to extensions but this is what we are using for now!
                editor.extensionStorage._notebookLogic = mountedNotebookLogic

                const notebookEditor: NotebookEditor = {
                    ...createEditor(editor),
                    findCommentPosition: (markId: string) => findCommentPosition(editor, markId),
                    removeComment: (pos: number) => removeCommentMark(editor, pos),
                    getText: () => textContent(editor.state.doc),
                }

                setEditor(notebookEditor)
            }}
        >
            <FloatingSuggestions />
            <InlineMenu
                extra={(editor) =>
                    hasDiscussions && !editor.isActive('comment') ? (
                        <>
                            <LemonDivider vertical />
                            <LemonButton
                                onClick={() => {
                                    const markId = uuid()
                                    editor.setMark(markId)
                                    mountedNotebookLogic.actions.insertComment({ type: 'mark', id: markId })
                                }}
                                icon={<IconComment className="w-4 h-4" />}
                                size="small"
                            />
                        </>
                    ) : null
                }
            />
        </RichContentEditor>
    )
}

function getNodeBeforeActiveNode(editor: TTEditor): RichContentNode | null {
    const { doc, selection } = editor.state
    const currentIndex = doc.resolve(selection.$anchor.pos).index(0)
    return doc.maybeChild(currentIndex - 1)
}

function findCommentPosition(editor: TTEditor, markId: string): number | null {
    let result = null
    const doc = editor.state.doc
    doc.descendants((node, pos) => {
        const mark = node.marks.find((mark) => mark.type.name === 'comment' && mark.attrs.id === markId)
        if (mark) {
            result = pos
            return
        }
    })
    return result
}

function removeCommentMark(editor: TTEditor, pos: number): void {
    editor
        .chain()
        .setNodeSelection(pos)
        .unsetMark('comment', { extendEmptyMarkRange: true })
        .setNodeSelection(0) // need to reset the selection so that the editor does not complain after mark is removed
        .run()
}
