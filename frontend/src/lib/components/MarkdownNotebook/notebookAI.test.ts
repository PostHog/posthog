import { insertNotebookAIFollowUpPromptAfterResponse, replaceNotebookAIResponseMarkdown } from './notebookAI'

function replaceMarkdown(
    markdown: string,
    responseNodeIndex: number,
    replacementMarkdown: string,
    replacedNodeCount: number = 1
): string {
    return replaceNotebookAIResponseMarkdown(markdown, responseNodeIndex, replacementMarkdown, replacedNodeCount)
        .markdown
}

describe('notebookAI', () => {
    it('replaces the AI response row with assistant markdown', () => {
        const markdown = '# Notebook\n\nThinking...'

        expect(replaceMarkdown(markdown, 1, 'Here is the answer.\n\n- First\n- Second')).toEqual(
            '# Notebook\n\nHere is the answer.\n\n- First\n- Second'
        )
    })

    it('strips echoed notebook context before replacing the AI response row', () => {
        const markdown = "# This is a new notebook\n\nLet's write some text\n\nThinking..."

        expect(
            replaceMarkdown(
                markdown,
                2,
                "# This is a new notebook\n\nLet's write some text\n\nThinking...\n\nJoke setup.\n\nPunchline."
            )
        ).toEqual("# This is a new notebook\n\nLet's write some text\n\nJoke setup.\n\nPunchline.")
    })

    it('strips echoed notebook context when the AI leaves the response placeholder at the end', () => {
        const markdown = '# New notebook\n\nThis is a random notebook\n\nThinking...'

        expect(
            replaceMarkdown(
                markdown,
                2,
                '# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.\n\nThinking...'
            )
        ).toEqual('# New notebook\n\nThis is a random notebook\n\nJames Hawkins co-founded PostHog.')
    })

    it('strips stale echoed context when the user edits before the AI response while streaming', () => {
        const markdown =
            "# Hello world\n\nlet's talk..... if i type here while it's thinking, things get duplicated...\n\nThinking..."

        expect(
            replaceMarkdown(markdown, 2, "# Hello world\n\nlet's talk.....\n\nJames Hawkins co-founded PostHog.")
        ).toEqual(
            "# Hello world\n\nlet's talk..... if i type here while it's thinking, things get duplicated...\n\nJames Hawkins co-founded PostHog."
        )
    })

    it('keeps assistant markdown that does not echo the AI response placeholder', () => {
        const markdown = '# Notebook\n\nThinking...'

        expect(replaceMarkdown(markdown, 1, '# Notebook\n\nA generated answer.')).toEqual(
            '# Notebook\n\n# Notebook\n\nA generated answer.'
        )
    })

    it('ignores an assistant response that only echoes the notebook context', () => {
        const markdown = '# Notebook\n\nThinking...'

        expect(replaceMarkdown(markdown, 1, '# Notebook\n\nThinking...')).toEqual(markdown)
    })

    it('replaces a previously streamed multi-block AI response', () => {
        const markdown = '# Notebook\n\nFirst paragraph\n\nSecond paragraph'

        expect(replaceMarkdown(markdown, 2, 'First paragraph\n\nSecond paragraph\n\nThird paragraph', 2)).toEqual(
            '# Notebook\n\nFirst paragraph\n\nSecond paragraph\n\nThird paragraph'
        )
    })

    it('returns the updated response row index for streamed replacements', () => {
        const firstResult = replaceNotebookAIResponseMarkdown(
            '# Notebook\n\nThinking...',
            1,
            'First paragraph\n\nSecond paragraph'
        )

        expect(firstResult).toEqual({
            markdown: '# Notebook\n\nFirst paragraph\n\nSecond paragraph',
            responseNodeIndex: 2,
        })

        const secondResult = replaceNotebookAIResponseMarkdown(
            firstResult.markdown,
            firstResult.responseNodeIndex,
            'First paragraph\n\nSecond paragraph\n\nThird paragraph',
            2
        )

        expect(secondResult).toEqual({
            markdown: '# Notebook\n\nFirst paragraph\n\nSecond paragraph\n\nThird paragraph',
            responseNodeIndex: 3,
        })
    })

    it('normalizes saved insight tags from AI output before insertion', () => {
        const markdown = '# Notebook\n\nThinking...'

        expect(
            replaceMarkdown(
                markdown,
                1,
                '## Browsers in use\n\n<insight>uONk</insight>\n\nThe chart shows browser usage.'
            )
        ).toEqual(
            '# Notebook\n\n## Browsers in use\n\n<Query query={{"kind":"SavedInsightNode","shortId":"uONk"}} />\n\nThe chart shows browser usage.'
        )
    })

    it('inserts a follow-up prompt after the AI response row', () => {
        const markdown = '# Notebook\n\nAnswer text'

        expect(insertNotebookAIFollowUpPromptAfterResponse(markdown, 1, '<Prompt question="" />')).toEqual(
            '# Notebook\n\nAnswer text\n\n<Prompt question="" />'
        )
    })

    it('does not treat a prompt inside a code block as an existing follow-up prompt', () => {
        const markdown = '# Notebook\n\n```md\n<Prompt question="" />\n```\n\nAnswer text'

        expect(insertNotebookAIFollowUpPromptAfterResponse(markdown, 2, '<Prompt question="" />')).toEqual(
            '# Notebook\n\n```md\n<Prompt question="" />\n```\n\nAnswer text\n\n<Prompt question="" />'
        )
    })

    it('does not insert duplicate empty follow-up prompts', () => {
        const markdown = '# Notebook\n\n<Prompt question="" />\n\nAnswer text'

        expect(insertNotebookAIFollowUpPromptAfterResponse(markdown, 2, '<Prompt question="" />')).toEqual(markdown)
    })

    it('keeps the AI response anchored on the final list item before a follow-up prompt', () => {
        const markdown = '# Notebook\n\n- First\n- Second'

        expect(insertNotebookAIFollowUpPromptAfterResponse(markdown, 1, '<Prompt question="" />')).toEqual(
            '# Notebook\n\n- First\n- Second\n\n<Prompt question="" />'
        )
    })
})
