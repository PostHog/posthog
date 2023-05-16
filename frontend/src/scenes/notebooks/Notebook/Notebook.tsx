import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import ExtensionDocument from '@tiptap/extension-document'
import ExtensionPlaceholder from '@tiptap/extension-placeholder'
import { useEffect, useMemo } from 'react'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import MonacoEditor from '@monaco-editor/react'
import { Spinner } from 'lib/lemon-ui/Spinner'
import './Notebook.scss'

import { NotebookNodeFlag } from '../Nodes/NotebookNodeFlag'
import { NotebookNodeQuery } from 'scenes/notebooks/Nodes/NotebookNodeQuery'
import { NotebookNodeInsight } from 'scenes/notebooks/Nodes/NotebookNodeInsight'
import { NotebookNodeRecording } from 'scenes/notebooks/Nodes/NotebookNodeRecording'
import { NotebookNodePlaylist } from 'scenes/notebooks/Nodes/NotebookNodePlaylist'
import { NotebookNodePerson } from '../Nodes/NotebookNodePerson'
import { NotebookNodeLink } from '../Nodes/NotebookNodeLink'
import { sampleOne } from 'lib/utils'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export type NotebookProps = {
    id: string
    sourceMode?: boolean
    editable?: boolean
}

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Notebook({ id, sourceMode, editable = false }: NotebookProps): JSX.Element {
    const logic = notebookLogic({ id })
    const { notebook, content, notebookLoading } = useValues(logic)
    const { setEditorRef, onEditorUpdate } = useActions(logic)

    const headingPlaceholder = useMemo(() => sampleOne(PLACEHOLDER_TITLES), [id])

    const editor = useEditor({
        extensions: [
            CustomDocument,
            StarterKit.configure({
                document: false,
            }),
            ExtensionPlaceholder.configure({
                placeholder: ({ node }) => {
                    if (node.type.name === 'heading' && node.attrs.level === 1) {
                        return `Untitled - maybe.. "${headingPlaceholder}"`
                    }

                    if (node.type.name === 'heading') {
                        return `Heading ${node.attrs.level}`
                    }

                    return ''
                },
            }),
            NotebookNodeLink,

            NotebookNodeInsight,
            NotebookNodeQuery,
            NotebookNodeRecording,
            NotebookNodePlaylist,
            NotebookNodePerson,
            NotebookNodeFlag,

            // Ensure this is last as a fallback for all PostHog links
            // LinkExtension.configure({}),
        ],
        // This is only the default content. It is not reactive
        content,
        // content: `<h1>RFC: Notebooks </h1><h2><em>or:</em> How to convince everyone that this is a great idea 🤔</h2><p></p><ol><li><p>Involve HogQL somehow</p></li><li><p>Mention <strong>10x</strong> at least ten times</p></li><li><p>Talk about how awesome it is that we can use &lt;Query&gt;</p></li><li><p>Dad jokes</p></li><li><p>🥳</p></li></ol><p></p><p>Let's start with an <strong>Insight </strong>showing how the product will sky-rocket once Notebooks are released:</p><p></p><ph-insight shortid=\"OlmLXv6Q\"></ph-insight><p></p><p></p><p>Numbers are great and all but we should check out <strong>related Recordings </strong>of people who did the thing in the previous Insight. If we get this right <strong>clicking on a point in the graph</strong> would open a preview below which can then be stuck to the Notebook if desired. (Think opening a file in VSCode and it staying open once saved or double clicked.</p><p></p><ph-recording-playlist filters=\"[object Object]\"></ph-recording-playlist><p></p><p></p><p>Watching these recordings made me think - <em>\"I wonder what people are fitting into this insight I'm building up\"</em> so using the magical world of Data Exploration I duplicate the <strong>Playlist</strong> node and convert it to a <strong>Persons</strong> table, now seeing all Persons who match the filters from before</p><p></p><p></p><ph-query query=\"{&quot;kind&quot;:&quot;DataTableNode&quot;,&quot;columns&quot;:[&quot;person&quot;,&quot;id&quot;,&quot;created_at&quot;,&quot;person.$delete&quot;],&quot;source&quot;:{&quot;kind&quot;:&quot;PersonsNode&quot;,&quot;properties&quot;:[{&quot;type&quot;:&quot;person&quot;,&quot;key&quot;:&quot;$browser&quot;,&quot;operator&quot;:&quot;exact&quot;,&quot;value&quot;:&quot;Chrome&quot;}]}}\"></ph-query><p></p><p></p><p></p><p>I think these are our <strong>ICP!!!!</strong></p><ph-query query=\"{&quot;kind&quot;:&quot;DataTableNode&quot;,&quot;full&quot;:true,&quot;source&quot;:{&quot;kind&quot;:&quot;EventsQuery&quot;,&quot;select&quot;:[&quot;*&quot;,&quot;event&quot;,&quot;person&quot;],&quot;orderBy&quot;:[&quot;timestamp DESC&quot;],&quot;after&quot;:&quot;-24h&quot;,&quot;limit&quot;:100,&quot;event&quot;:&quot;$pageview&quot;},&quot;propertiesViaUrl&quot;:true,&quot;showSavedQueries&quot;:true}\"></ph-query><p></p><p></p><h1>Finalising my argument</h1><p></p><p>Now that I have a bunch of insights and dynamic data, maybe I want to freeze some points in time for the future. Forget <strong>Pinned Recordings</strong> or <strong>Saved Insights</strong> - that's so 1995.</p><p></p><p>As this is more like an editable document I could just <strong>pull</strong> <strong>Recordings that I like</strong> into the document as standalone items. By default they would start in a <strong>Preview </strong>state (as would many components to aid rendering and readability) but with the ability to expand this out</p><p></p><p>Whilst I'm here I might mention <strong>@Charles </strong>that this is a great thing to talk about for our next marketing push. He could even copy and pate sections of this Notebook into his own <strong>Public Release Notebook</strong> which could then be shared publicly, even as a template for others to import and use...</p><h1>🤔🤔🤔🤔</h1><p></p><p></p><p></p><ph-recording sessionrecordingid=\"186cc347fb825b9-0589308f1c8c0b-1e525634-16a7f0-186cc347fb92fd9\"></ph-recording><ph-recording sessionrecordingid=\"186cc347fb825b9-0589308f1c8c0b-1e525634-16a7f0-186cc347fb92fd9\"></ph-recording><p></p><p>As this is a document we could \"<strong>FREEZE\" </strong>any Query by simply storing the result data <em>in the Notebook</em>. Not only does this make it much faster to load but fits well into the general concept used elsewhere of a Notebook.</p><ph-insight shortid=\"OlmLXv6Q\"></ph-insight><p></p><p></p><h1>Big picture thinking...</h1><p></p><p>One day we won't just have Clickhouse Event data and Recordings but potentially Exceptions, Stripe data, Relational DB connections. We're going to need a way to explore this dynamically and usefully. Most Data Scientist-y types are used to <strong>Python Notebooks</strong> which work like this:</p><p></p><ol><li><p>I build a query in Python or SQL etc.</p></li><li><p>I can use other parts of the Notebook as an input source (e.g. the results from the Insight above can be available as a variable)</p></li><li><p>I write my code and when I run it, the result is stored <strong>in the Notebook</strong> and any other queries depending on it are updated.</p></li><li><p>The output of the code snippet is rendered automatically with controls to change how it looks (very similar to the Data Exploration we already have...)</p></li></ol><p></p><p></p><p></p><ph-query query=\"{&quot;kind&quot;:&quot;DataTableNode&quot;,&quot;full&quot;:true,&quot;source&quot;:{&quot;kind&quot;:&quot;HogQLQuery&quot;,&quot;query&quot;:&quot;   select event,\\n          person.properties.email,\\n          properties.$browser,\\n          count()\\n     from events\\n    where timestamp > now () - interval 1 day\\n      and person.properties.email is not null\\n group by event,\\n          properties.$browser,\\n          person.properties.email\\n order by count() desc\\n    limit 100&quot;}}\"></ph-query><p></p><p></p><p></p><p></p>`,
        editorProps: {
            attributes: {
                class: 'NotebookEditor',
            },
            handleDrop: (view, event, _slice, moved) => {
                if (!moved && event.dataTransfer) {
                    const text = event.dataTransfer.getData('text/plain')

                    if (text.indexOf(window.location.origin) === 0) {
                        // PostHog link - ensure this gets input as a proper link
                        const coordinates = view.posAtCoords({ left: event.clientX, top: event.clientY })

                        if (!coordinates) {
                            return false
                        }

                        editor?.chain().focus().setTextSelection(coordinates.pos).run()
                        view.pasteText(text)

                        return true
                    }

                    if (event.dataTransfer.files && event.dataTransfer.files[0]) {
                        // if dropping external files
                        const file = event.dataTransfer.files[0] // the dropped file

                        console.log('TODO: Dropped file!', file)
                        // TODO: Detect if it is an image and add image upload handler

                        return true
                    }
                }

                return false
            },
        },
        onUpdate: ({}) => {
            onEditorUpdate()
        },
    })

    useEffect(() => {
        if (editor) {
            setEditorRef(editor)
        }
    }, [editor])

    useEffect(() => {
        editor?.setEditable(editable && !!notebook)
    }, [editable, editor, notebook])

    return (
        <BindLogic logic={notebookLogic} props={{ id }}>
            <div className="Notebook">
                {/* {editor && (
                <FloatingMenu editor={editor} tippyOptions={{ duration: 100 }} className="flex items-center gap-2">
                    <LemonButton
                        size="small"
                        status="primary-alt"
                        noPadding
                        onClick={() => editor.chain().focus().insertContent('<ph-query />').run()}
                    >
                        Query
                    </LemonButton>

                    <LemonButton
                        size="small"
                        status="primary-alt"
                        noPadding
                        onClick={() => editor.chain().focus().insertContent('<ph-playlist />').run()}
                    >
                        Recordings
                    </LemonButton>

                    <LemonButton
                        size="small"
                        status="primary-alt"
                        noPadding
                        onClick={() => editor.chain().focus().insertContent('<ph-embed />').run()}
                    >
                        Embed
                    </LemonButton>
                </FloatingMenu>
            )} */}

                {!notebook && notebookLoading ? (
                    <div className="space-y-4 px-8 py-4">
                        <LemonSkeleton className="w-1/2 h-8" />
                        <LemonSkeleton className="w-1/3 h-4" />
                        <LemonSkeleton className="h-4" />
                        <LemonSkeleton className="h-4" />
                    </div>
                ) : !sourceMode ? (
                    <EditorContent editor={editor} className="flex flex-col flex-1 overflow-y-auto" />
                ) : (
                    <AutoSizer disableWidth>
                        {({ height }) => (
                            <MonacoEditor
                                theme="vs-light"
                                language="json"
                                value={JSON.stringify(editor?.getJSON(), null, 2) ?? ''}
                                height={height}
                                loading={<Spinner />}
                                onChange={(value) => {
                                    if (value) {
                                        try {
                                            editor?.chain().setContent(JSON.parse(value)).run()
                                        } catch (e) {
                                            console.error(e)
                                        }
                                    }
                                }}
                            />
                        )}
                    </AutoSizer>
                )}
            </div>
        </BindLogic>
    )
}
