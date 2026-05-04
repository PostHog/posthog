import { Extension } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { FloatingMenu } from '@tiptap/extension-floating-menu'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import TableOfContents, { getHierarchicalIndexes } from '@tiptap/extension-table-of-contents'
import { Placeholder } from '@tiptap/extensions'
import { collab } from '@tiptap/pm/collab'
import StarterKit, { StarterKitOptions } from '@tiptap/starter-kit'
import { useActions, useValues } from 'kea'
import { useThrottledCallback } from 'use-debounce'

import { IconComment } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { RichContentEditor } from 'lib/components/RichContentEditor'
import { RichContentNodeMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { RichContentNode, TTEditor } from 'lib/components/RichContentEditor/types'
import { createEditor } from 'lib/components/RichContentEditor/utils'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { uuid } from 'lib/utils'

import { MentionsExtension } from '../../../lib/components/RichContentEditor/MentionsExtension'
import { NotebookMarkComment } from '../Marks/NotebookMarkComment'
import { NotebookMarkLink } from '../Marks/NotebookMarkLink'
import { NotebookNodeBacklink } from '../Nodes/NotebookNodeBacklink'
import { NotebookNodeCohort } from '../Nodes/NotebookNodeCohort'
import { NotebookNodeCustomerJourney } from '../Nodes/NotebookNodeCustomerJourney/NotebookNodeCustomerJourney'
import { NotebookNodeDuckSQL } from '../Nodes/NotebookNodeDuckSQL'
import { NotebookNodeEarlyAccessFeature } from '../Nodes/NotebookNodeEarlyAccessFeature'
import { NotebookNodeEmbed } from '../Nodes/NotebookNodeEmbed'
import { NotebookNodeExperiment } from '../Nodes/NotebookNodeExperiment'
import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeFlagCodeExample } from '../Nodes/NotebookNodeFlagCodeExample'
import { NotebookNodeGroup } from '../Nodes/NotebookNodeGroup'
import { NotebookNodeGroupProperties } from '../Nodes/NotebookNodeGroupProperties'
import { NotebookNodeHogQL } from '../Nodes/NotebookNodeHogQL'
import { NotebookNodeImage } from '../Nodes/NotebookNodeImage'
import { NotebookNodeIssues } from '../Nodes/NotebookNodeIssues'
import { NotebookNodeLatex } from '../Nodes/NotebookNodeLatex'
import { NotebookNodeLLMTrace } from '../Nodes/NotebookNodeLLMTrace'
import { NotebookNodeMap } from '../Nodes/NotebookNodeMap'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'
import { NotebookNodePersonFeed } from '../Nodes/NotebookNodePersonFeed/NotebookNodePersonFeed'
import { NotebookNodePersonProperties } from '../Nodes/NotebookNodePersonProperties'
import { NotebookNodePlaylist } from '../Nodes/NotebookNodePlaylist'
import { NotebookNodePython } from '../Nodes/NotebookNodePython'
import { NotebookNodeQuery } from '../Nodes/NotebookNodeQuery'
import { NotebookNodeRecording } from '../Nodes/NotebookNodeRecording'
import { NotebookNodeRelatedGroups } from '../Nodes/NotebookNodeRelatedGroups'
import { NotebookNodeReplayTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { NotebookNodeSupportTickets } from '../Nodes/NotebookNodeSupportTickets'
import { NotebookNodeSurvey } from '../Nodes/NotebookNodeSurvey'
import { NotebookNodeTaskCreate } from '../Nodes/NotebookNodeTaskCreate'
import { NotebookNodeUsageMetrics } from '../Nodes/NotebookNodeUsageMetrics'
import { NotebookNodeZendeskTickets } from '../Nodes/NotebookNodeZendeskTickets'
import { FloatingSuggestions } from '../Suggestions/FloatingSuggestions'
import { insertionSuggestionsLogic } from '../Suggestions/insertionSuggestionsLogic'
import { NotebookEditor } from '../types'
import { textContent } from '../utils'
import { CollapsibleHeading } from './CollapsibleHeading'
import { DropAndPasteHandlerExtension } from './DropAndPasteHandlerExtension'
import { InlineMenu } from './InlineMenu'
import { notebookCollabLogic } from './notebookCollabLogic'
import { NotebookDefaultBlockOnEnter } from './NotebookDefaultBlockOnEnter'
import { notebookLogic } from './notebookLogic'
import { NotebookTrailingParagraph } from './NotebookTrailingParagraph'
import { RemotePresenceExtension } from './RemotePresenceExtension'
import { SlashCommandsExtension } from './SlashCommands'
import { TableMenu } from './TableMenu'

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

export function Editor(): JSX.Element {
    const { shortId, mode, isEditable, content, collabEnabled, notebook } = useValues(notebookLogic)
    const { setEditor, onEditorUpdate, onEditorSelectionUpdate, setTableOfContents, insertComment } =
        useActions(notebookLogic)
    const hasCollapsibleSections = useFeatureFlag('NOTEBOOKS_COLLAPSIBLE_SECTIONS')
    const { bindEditor } = useActions(notebookCollabLogic({ shortId }))
    const { clientID } = useValues(notebookCollabLogic({ shortId }))

    const { resetSuggestions, setPreviousNode } = useActions(insertionSuggestionsLogic)

    // Throttle setPreviousNode to avoid excessive calls during rapid selection changes
    const throttledSetPreviousNode = useThrottledCallback((editor: TTEditor) => {
        setPreviousNode(getNodeBeforeActiveNode(editor))
    }, 16) // ~60fps throttling

    const starterKitConfig: Partial<StarterKitOptions> = {
        document: false,
        gapcursor: false,
        link: false,
        trailingNode: false,
    }

    const useCollab = collabEnabled && !!notebook

    const extensions = [
        mode === 'notebook' ? CustomDocument : ExtensionDocument,
        StarterKit.configure(hasCollapsibleSections ? { ...starterKitConfig, heading: false } : starterKitConfig),
        TableOfContents.configure({
            getIndex: getHierarchicalIndexes,
            onUpdate(content) {
                setTableOfContents(content)
            },
        }),
        Placeholder.configure({
            placeholder: ({ node }: { node: any }) => {
                if (node.type.name === 'heading' && node.attrs.level === 1) {
                    return 'Untitled'
                }

                if (node.type.name === 'heading') {
                    return `Heading ${node.attrs.level}`
                }

                return ''
            },
        }),
        FloatingMenu.extend({
            onSelectionUpdate(this) {
                throttledSetPreviousNode(this.editor)
            },
            onUpdate(this) {
                throttledSetPreviousNode(this.editor)
                resetSuggestions()
            },
        }),
        Table,
        TableRow,
        TableHeader,
        TableCell,
        DropAndPasteHandlerExtension,
        TaskList,
        TaskItem.configure({ nested: true }),
        NotebookMarkLink,
        NotebookMarkComment,
        NotebookNodeLatex,
        NotebookNodeBacklink,
        NotebookNodeQuery,
        NotebookNodePython,
        NotebookNodeDuckSQL,
        NotebookNodeHogQL,
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
        NotebookNodePersonProperties,
        NotebookNodeGroupProperties,
        RichContentNodeMention,
        NotebookNodeEmbed,
        SlashCommandsExtension,
        MentionsExtension,
        NotebookNodePersonFeed,
        NotebookNodeMap,
        NotebookNodeTaskCreate,
        NotebookNodeLLMTrace,
        NotebookNodeIssues,
        NotebookNodeUsageMetrics,
        NotebookNodeZendeskTickets,
        NotebookNodeSupportTickets,
        NotebookNodeRelatedGroups,
        NotebookNodeCustomerJourney,
        NotebookTrailingParagraph,
        NotebookDefaultBlockOnEnter,
    ]

    if (useCollab) {
        extensions.push(
            Extension.create({
                name: 'collaboration',
                addProseMirrorPlugins() {
                    return [collab({ version: notebook.version, clientID })]
                },
            }),
            RemotePresenceExtension
        )
    }

    if (hasCollapsibleSections) {
        extensions.push(CollapsibleHeading.configure())
    }

    return (
        <RichContentEditor
            // Collab suffix forces editor to re-initialize so the collab plugin is present
            logicKey={`Notebook.${shortId}${useCollab ? '-collab' : ''}`}
            extensions={extensions}
            disabled={!isEditable}
            className="NotebookEditor flex flex-col flex-1"
            initialContent={content}
            onUpdate={onEditorUpdate}
            onSelectionUpdate={onEditorSelectionUpdate}
            onCreate={(editor) => {
                const notebookEditor: NotebookEditor = {
                    ...createEditor(editor),
                    findCommentPosition: (markId: string) => findCommentPosition(editor, markId),
                    removeComment: (pos: number) => removeCommentMark(editor, pos),
                    getText: () => textContent(editor.state.doc),
                }

                setEditor(notebookEditor)

                if (useCollab) {
                    bindEditor(editor)
                }
            }}
        >
            <FloatingSuggestions />
            {isEditable && <TableMenu />}
            <InlineMenu
                extra={(editor) =>
                    !editor.isSelectionFullyWithinSingleMark('comment') ? (
                        <>
                            <LemonDivider vertical />
                            <LemonButton
                                onClick={() => {
                                    const markId = uuid()
                                    editor.setMark(markId)
                                    insertComment({ type: 'mark', id: markId })
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
    let result: number | null = null
    const doc = editor.state.doc
    doc.descendants((node, pos) => {
        const mark = node.marks.find((mark) => mark.type.name === 'comment' && mark.attrs.id === markId)
        if (mark) {
            // Same id can appear on multiple text nodes; use the start of the marked run.
            if (result === null || pos < result) {
                result = pos
            }
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
