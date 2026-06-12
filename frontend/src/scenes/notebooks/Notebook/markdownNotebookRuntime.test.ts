import {
    findNotebookAIChatTag,
    getNotebookAIChatMarker,
    insertMarkdownAfterNotebookAIChatMarker,
    preserveNotebookAIChatMarker,
} from './markdownNotebookRuntime'

const CHAT_ID = '835f09ed-e58a-4a4a-93c3-813ced0d3e55'
const CHAT_MARKER = getNotebookAIChatMarker(CHAT_ID)
const CHAT_TAG_WITH_PROPS = `<Chat id="${CHAT_ID}" lastAnswer="The funnel improved" title="Funnel chat" />`

describe('markdownNotebookRuntime markers', () => {
    describe('preserveNotebookAIChatMarker', () => {
        it('keeps the next markdown untouched when it still contains the marker', () => {
            const nextMarkdown = `# Title\n\n${CHAT_MARKER}\n\nNew paragraph`

            expect(preserveNotebookAIChatMarker(nextMarkdown, `# Title\n\n${CHAT_MARKER}`, CHAT_ID)).toEqual(
                nextMarkdown
            )
        })

        it('re-anchors a dropped marker after the block that preceded it', () => {
            const currentMarkdown = `# Title\n\nIntro paragraph\n\n${CHAT_MARKER}\n\nTail paragraph`
            const nextMarkdown = '# Title\n\nIntro paragraph\n\nGenerated content\n\nTail paragraph'

            expect(preserveNotebookAIChatMarker(nextMarkdown, currentMarkdown, CHAT_ID)).toEqual(
                `# Title\n\nIntro paragraph\n\n${CHAT_MARKER}\n\nGenerated content\n\nTail paragraph`
            )
        })

        it('re-anchors a dropped marker at the start when it was the first block', () => {
            const currentMarkdown = `${CHAT_MARKER}\n\nTail paragraph`
            const nextMarkdown = 'Generated content\n\nTail paragraph'

            expect(preserveNotebookAIChatMarker(nextMarkdown, currentMarkdown, CHAT_ID)).toEqual(
                `${CHAT_MARKER}\n\nGenerated content\n\nTail paragraph`
            )
        })

        it('appends a dropped marker when its anchor block no longer exists', () => {
            const currentMarkdown = `Removed anchor\n\n${CHAT_MARKER}`
            const nextMarkdown = 'Entirely new content'

            expect(preserveNotebookAIChatMarker(nextMarkdown, currentMarkdown, CHAT_ID)).toEqual(
                `Entirely new content\n\n${CHAT_MARKER}`
            )
        })

        it('returns the next markdown unchanged when the marker was not present before', () => {
            expect(preserveNotebookAIChatMarker('New content', 'Old content', CHAT_ID)).toEqual('New content')
        })

        it('restores the accumulated chat props when the AI echoes the bare marker', () => {
            // The AI is shown a marker and echoes it bare; the editor owns lastAnswer/title.
            const currentMarkdown = `# Title\n\n${CHAT_TAG_WITH_PROPS}`
            const nextMarkdown = `# Title\n\n${CHAT_MARKER}\n\nGenerated content`

            expect(preserveNotebookAIChatMarker(nextMarkdown, currentMarkdown, CHAT_ID)).toEqual(
                `# Title\n\n${CHAT_TAG_WITH_PROPS}\n\nGenerated content`
            )
        })

        it('re-anchors a chat tag with props when the AI dropped the marker', () => {
            const currentMarkdown = `Intro paragraph\n\n${CHAT_TAG_WITH_PROPS}`
            const nextMarkdown = 'Intro paragraph\n\nGenerated content'

            expect(preserveNotebookAIChatMarker(nextMarkdown, currentMarkdown, CHAT_ID)).toEqual(
                `Intro paragraph\n\n${CHAT_TAG_WITH_PROPS}\n\nGenerated content`
            )
        })
    })

    describe('insertMarkdownAfterNotebookAIChatMarker', () => {
        it('inserts the block right after the chat marker', () => {
            const currentMarkdown = `# Title\n\n${CHAT_MARKER}\n\nTail paragraph`

            expect(insertMarkdownAfterNotebookAIChatMarker('<Query query={{}} />', currentMarkdown, CHAT_ID)).toEqual(
                `# Title\n\n${CHAT_MARKER}\n\n<Query query={{}} />\n\nTail paragraph`
            )
        })

        it('appends the block when the marker is missing', () => {
            expect(insertMarkdownAfterNotebookAIChatMarker('New block', '# Title', CHAT_ID)).toEqual(
                '# Title\n\nNew block'
            )
        })

        it('does not insert a block that already exists in the markdown', () => {
            const currentMarkdown = `# Title\n\n${CHAT_MARKER}\n\nExisting block`

            expect(insertMarkdownAfterNotebookAIChatMarker('Existing block', currentMarkdown, CHAT_ID)).toEqual(
                currentMarkdown
            )
        })

        it('finds the chat even after it accumulated props', () => {
            const currentMarkdown = `# Title\n\n${CHAT_TAG_WITH_PROPS}\n\nTail paragraph`

            expect(insertMarkdownAfterNotebookAIChatMarker('<Query query={{}} />', currentMarkdown, CHAT_ID)).toEqual(
                `# Title\n\n${CHAT_TAG_WITH_PROPS}\n\n<Query query={{}} />\n\nTail paragraph`
            )
        })
    })

    describe('findNotebookAIChatTag', () => {
        it('matches the bare marker and prop-laden tags, but not other chats', () => {
            expect(findNotebookAIChatTag(`a\n\n${CHAT_MARKER}\n\nb`, CHAT_ID)).toEqual({
                index: 3,
                tag: CHAT_MARKER,
            })
            expect(findNotebookAIChatTag(CHAT_TAG_WITH_PROPS, CHAT_ID)?.tag).toEqual(CHAT_TAG_WITH_PROPS)
            expect(findNotebookAIChatTag('<Chat id="other-chat" />', CHAT_ID)).toBeNull()
        })
    })
})
