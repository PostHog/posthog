import { serializeMarkdownNotebook } from './markdown'
import {
    NOTEBOOK_AI_AGENT_ID,
    NOTEBOOK_AI_AGENT_NAME,
    appendNotebookAgentCommentReplyToMarkdown,
    applyNotebookAgentArtifactMarkdown,
    createNotebookAgent,
    getNotebookAgentAIQuery,
    getNotebookAgentAvatarLabel,
    getNotebookAgentClientId,
    getNotebookAgentIdFromClientId,
    getNotebookAgentsFromMarkdown,
    insertMarkdownAfterNotebookAIAgentCursor,
    insertNotebookAIFollowUpPromptAfterCursor,
    insertNotebookAgentMarkdownAfterRef,
    makeNotebookAgentNode,
    normalizeNotebookAIAgentArtifactMarkdown,
    preserveNotebookAIAgentNode,
    replaceNotebookAIAgentCursorMarkdown,
    removeNotebookAgentFromMarkdown,
    stripNotebookAgentsFromMarkdown,
} from './notebookAgents'

describe('notebookAgents', () => {
    it('creates the singleton AI agent and round-trips agent tags', () => {
        const agent = createNotebookAgent()
        const markdown = serializeMarkdownNotebook({
            type: 'doc',
            nodes: [
                {
                    ...makeNotebookAgentNode({ ...agent, cursor: { nodeIndex: 1, offset: 4 } }),
                    id: 'agent-node',
                },
            ],
            errors: [],
        })

        expect(agent).toEqual({ id: NOTEBOOK_AI_AGENT_ID, name: NOTEBOOK_AI_AGENT_NAME })
        expect(getNotebookAgentsFromMarkdown(markdown)).toEqual([
            {
                id: NOTEBOOK_AI_AGENT_ID,
                name: NOTEBOOK_AI_AGENT_NAME,
                cursor: { nodeIndex: 1, offset: 4, listItemIndex: undefined },
            },
        ])
    })

    it('uses AI as the presence label', () => {
        const agent = { id: NOTEBOOK_AI_AGENT_ID, name: NOTEBOOK_AI_AGENT_NAME }

        expect(getNotebookAgentAvatarLabel(agent)).toEqual('AI')
    })

    it('removes persisted agents and maps client ids back to agent ids', () => {
        const markdown = '# Notebook\n\n<Agent id="ai" name="AI" />\n\nBody'

        expect(removeNotebookAgentFromMarkdown(markdown, NOTEBOOK_AI_AGENT_ID)).toEqual('# Notebook\n\nBody')
        expect(getNotebookAgentIdFromClientId(getNotebookAgentClientId({ id: NOTEBOOK_AI_AGENT_ID }))).toEqual(
            NOTEBOOK_AI_AGENT_ID
        )
    })

    it('strips persisted agents from markdown', () => {
        expect(stripNotebookAgentsFromMarkdown('# Notebook\n\n<Agent id="ai" name="AI" />\n\nBody')).toEqual(
            '# Notebook\n\nBody'
        )
    })

    it('preserves the singleton AI agent across replacement markdown', () => {
        expect(
            preserveNotebookAIAgentNode(
                '# Rewritten notebook',
                '# Original notebook\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1}} />'
            )
        ).toEqual('# Rewritten notebook\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1}} />')
    })

    it('replaces the AI cursor row with assistant markdown', () => {
        const markdown = '# Notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":11}} />'

        expect(replaceNotebookAIAgentCursorMarkdown(markdown, 'Here is the answer.\n\n- First\n- Second')).toEqual(
            '# Notebook\n\nHere is the answer.\n\n- First\n- Second\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":6,"listItemIndex":1}} />'
        )
    })

    it('strips echoed notebook context before replacing the AI cursor row', () => {
        const markdown =
            '# This is a new notebook\n\nLet\'s write some text\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'

        expect(
            replaceNotebookAIAgentCursorMarkdown(
                markdown,
                "# This is a new notebook\n\nLet's write some text\n\nThinking...\n\nJoke setup.\n\nPunchline."
            )
        ).toEqual(
            '# This is a new notebook\n\nLet\'s write some text\n\nJoke setup.\n\nPunchline.\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":3,"offset":10}} />'
        )
    })

    it('strips echoed notebook context when the AI leaves the cursor placeholder at the end', () => {
        const markdown =
            '# New notebook\n\nThis is a random notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'

        expect(
            replaceNotebookAIAgentCursorMarkdown(
                markdown,
                '# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.\n\nThinking...'
            )
        ).toEqual(
            '# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":33}} />'
        )
    })

    it('strips stale echoed context when the user edits before the AI cursor while streaming', () => {
        const markdown =
            '# Hello world\n\nlet\'s talk..... if i type here while it\'s thinking, things get duplicated...\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'

        expect(
            replaceNotebookAIAgentCursorMarkdown(
                markdown,
                "# Hello world\n\nlet's talk.....\n\nJames Hawkins co-founded PostHog."
            )
        ).toEqual(
            '# Hello world\n\nlet\'s talk..... if i type here while it\'s thinking, things get duplicated...\n\nJames Hawkins co-founded PostHog.\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":33}} />'
        )
    })

    it('keeps assistant markdown that does not echo the AI cursor placeholder', () => {
        const markdown = '# Notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":11}} />'

        expect(replaceNotebookAIAgentCursorMarkdown(markdown, '# Notebook\n\nA generated answer.')).toEqual(
            '# Notebook\n\n# Notebook\n\nA generated answer.\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":19}} />'
        )
    })

    it('ignores an assistant response that only echoes the notebook context', () => {
        const markdown = '# Notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":11}} />'

        expect(replaceNotebookAIAgentCursorMarkdown(markdown, '# Notebook\n\nThinking...')).toEqual(markdown)
    })

    it('normalizes full notebook artifacts that echo context before the answer', () => {
        const currentMarkdown =
            '# New notebook\n\nThis is a random notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'
        const artifactMarkdown =
            '# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.\n\nThinking...'

        expect(normalizeNotebookAIAgentArtifactMarkdown(artifactMarkdown, currentMarkdown)).toEqual(
            '# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.'
        )
    })

    it('normalizes full notebook artifacts with stale context while the user edits before the AI cursor', () => {
        const currentMarkdown =
            '# Hello world\n\nlet\'s talk..... if i type here while it\'s thinking, things get duplicated...\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'
        const artifactMarkdown = "# Hello world\n\nlet's talk.....\n\nJames Hawkins co-founded PostHog.\n\nThinking..."

        expect(normalizeNotebookAIAgentArtifactMarkdown(artifactMarkdown, currentMarkdown)).toEqual(
            "# Hello world\n\nlet's talk..... if i type here while it's thinking, things get duplicated...\n\nJames Hawkins co-founded PostHog."
        )
    })

    it('normalizes full notebook artifacts that duplicate context twice', () => {
        const currentMarkdown =
            '# New notebook\n\nThis is a random notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'
        const artifactMarkdown =
            '# New notebook\n\nThis is a random notebook\n\n# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.\n\nThinking...'

        expect(normalizeNotebookAIAgentArtifactMarkdown(artifactMarkdown, currentMarkdown)).toEqual(
            '# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.'
        )
    })

    it('replaces a previously streamed multi-block AI response', () => {
        const markdown =
            '# Notebook\n\nFirst paragraph\n\nSecond paragraph\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":16}} />'

        expect(
            replaceNotebookAIAgentCursorMarkdown(markdown, 'First paragraph\n\nSecond paragraph\n\nThird paragraph', 2)
        ).toEqual(
            '# Notebook\n\nFirst paragraph\n\nSecond paragraph\n\nThird paragraph\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":3,"offset":15}} />'
        )
    })

    it('normalizes saved insight tags from AI output before insertion', () => {
        const markdown = '# Notebook\n\nThinking...\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":11}} />'

        expect(
            replaceNotebookAIAgentCursorMarkdown(
                markdown,
                '## Browsers in use\n\n<insight>uONk</insight>\n\nThe chart shows browser usage.'
            )
        ).toEqual(
            '# Notebook\n\n## Browsers in use\n\n<Query query={{"kind":"SavedInsightNode","shortId":"uONk"}} />\n\nThe chart shows browser usage.\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":3,"offset":30}} />'
        )
    })

    it('inserts artifact markdown after the AI cursor row', () => {
        const markdown =
            '# Notebook\n\nWorking on it\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":13}} />'

        expect(
            insertMarkdownAfterNotebookAIAgentCursor(markdown, '<Query query={{"kind":"DataTableNode"}} />')
        ).toEqual(
            '# Notebook\n\nWorking on it\n\n<Query query={{"kind":"DataTableNode"}} />\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2}} />'
        )
    })

    it('inserts a follow-up prompt and keeps the AI cursor before it', () => {
        const markdown = '# Notebook\n\nAnswer text\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":11}} />'

        expect(insertNotebookAIFollowUpPromptAfterCursor(markdown, '<Prompt question="" />')).toEqual(
            '# Notebook\n\nAnswer text\n\n<Prompt question="" />\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":11}} />'
        )
    })

    it('does not treat a prompt inside a code block as an existing follow-up prompt', () => {
        const markdown =
            '# Notebook\n\n```md\n<Prompt question="" />\n```\n\nAnswer text\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'

        expect(insertNotebookAIFollowUpPromptAfterCursor(markdown, '<Prompt question="" />')).toEqual(
            '# Notebook\n\n```md\n<Prompt question="" />\n```\n\nAnswer text\n\n<Prompt question="" />\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'
        )
    })

    it('does not insert duplicate empty follow-up prompts', () => {
        const markdown =
            '# Notebook\n\n<Prompt question="" />\n\nAnswer text\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":2,"offset":11}} />'

        expect(insertNotebookAIFollowUpPromptAfterCursor(markdown, '<Prompt question="" />')).toEqual(markdown)
    })

    it('keeps the AI cursor on the final list item before a follow-up prompt', () => {
        const markdown =
            '# Notebook\n\n- First\n- Second\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":6,"listItemIndex":1}} />'

        expect(insertNotebookAIFollowUpPromptAfterCursor(markdown, '<Prompt question="" />')).toEqual(
            '# Notebook\n\n- First\n- Second\n\n<Prompt question="" />\n\n<Agent id="ai" name="AI" cursor={{"nodeIndex":1,"offset":6,"listItemIndex":1}} />'
        )
    })

    it('builds an agent query for the LLM without generating the response locally', () => {
        const query = getNotebookAgentAIQuery({
            agent: { id: NOTEBOOK_AI_AGENT_ID, name: NOTEBOOK_AI_AGENT_NAME },
            promptText: 'Tell me a joke',
            refId: 'ref-1',
        })

        expect(query).toContain(NOTEBOOK_AI_AGENT_NAME)
        expect(query).toContain('Tell me a joke')
        expect(query).toContain('notebook artifact')
        expect(query).not.toContain('Why did')
    })

    it('appends LLM messages to the linked agent comment', () => {
        const markdown = '# Notebook\n\n<Comment ref="ref-1" replies={[]} />\n\n<ref id="ref-1">Add content</ref>'

        expect(
            appendNotebookAgentCommentReplyToMarkdown({
                markdown,
                refId: 'ref-1',
                agent: { id: NOTEBOOK_AI_AGENT_ID, name: NOTEBOOK_AI_AGENT_NAME },
                text: 'I will expand the outline and add examples.',
                replyId: 'assistant-1',
            })
        ).toContain('"text":"I will expand the outline and add examples."')
    })

    it('inserts LLM markdown after the referenced row', () => {
        const markdown =
            '# Notebook\n\n<Comment ref="ref-1" replies={[]} />\n\n<ref id="ref-1">Tell me a joke</ref>\n\nAfter'

        expect(
            insertNotebookAgentMarkdownAfterRef({
                markdown,
                refId: 'ref-1',
                insertedMarkdown: 'A generated answer from the LLM.',
            })
        ).toEqual(
            '# Notebook\n\n<Comment ref="ref-1" replies={[]} />\n\n<ref id="ref-1">Tell me a joke</ref>\n\nA generated answer from the LLM.\n\nAfter'
        )
    })

    it('applies replacement artifacts while preserving the agent anchor and persisted agent', () => {
        const markdown =
            '# Notebook\n\n<Comment ref="ref-1" replies={[]} />\n\n<ref id="ref-1">Redo this</ref>\n\nOld content\n\n<Agent id="ai" name="AI" />'

        expect(
            applyNotebookAgentArtifactMarkdown({
                markdown,
                refId: 'ref-1',
                artifactMarkdown: '# New notebook\n\nGenerated by the LLM.',
                replace: true,
            })
        ).toEqual(
            '<Comment ref="ref-1" replies={[]} />\n\n<ref id="ref-1">Redo this</ref>\n\n# New notebook\n\nGenerated by the LLM.\n\n<Agent id="ai" name="AI" />'
        )
    })

    it('does not duplicate the agent anchor when a replacement artifact already includes it', () => {
        const markdown =
            '# Notebook\n\nIntro\n\n<Comment ref="ref-1" replies={[{"id":"thinking","author":"AI","text":"Thinking..."}]} />\n\n<ref id="ref-1">What is up?</ref>\n\n<Agent id="ai" name="AI" />'
        const artifactMarkdown =
            '# Notebook\n\nIntro\n\n<Comment ref="ref-1" replies={[{"id":"thinking","author":"AI","text":"Thinking..."}]} />\n\nNot much, ready to help.\n\n<ref id="ref-1">What is up?</ref>'

        const result = applyNotebookAgentArtifactMarkdown({
            markdown,
            refId: 'ref-1',
            artifactMarkdown,
            replace: true,
        })

        expect(result).toEqual(`${artifactMarkdown}\n\n<Agent id="ai" name="AI" />`)
        expect(result.match(/<Comment ref="ref-1"/g)).toHaveLength(1)
        expect(result.match(/<ref id="ref-1">/g)).toHaveLength(1)
    })
})
