import {
    insertNotebookAIFollowUpPromptAfterResponse,
    rebaseNotebookAIResponseRange,
    replaceNotebookAIResponseMarkdown,
    streamNotebookAIResponseMarkdown,
} from './notebookAI'

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

    it('preserves edited previous AI blocks while streaming the active tail block', () => {
        const result = streamNotebookAIResponseMarkdown(
            '# Notebook\n\nHuman edited first paragraph\n\nSecond paragraph still writing',
            2,
            'First paragraph\n\nSecond paragraph finished\n\nThird paragraph still writing',
            2
        )

        expect(result).toEqual({
            markdown:
                '# Notebook\n\nHuman edited first paragraph\n\nSecond paragraph finished\n\nThird paragraph still writing',
            responseNodeIndex: 3,
            responseNodeCount: 3,
        })
    })

    it('continues streaming when an earlier generated AI block was deleted', () => {
        const result = streamNotebookAIResponseMarkdown(
            '# Notebook\n\nSecond paragraph\n\nThird paragraph still writing',
            3,
            'First paragraph\n\nSecond paragraph\n\nThird paragraph finished\n\nFourth paragraph still writing',
            3
        )

        expect(result).toEqual({
            markdown: '# Notebook\n\nSecond paragraph\n\nThird paragraph finished\n\nFourth paragraph still writing',
            responseNodeIndex: 3,
            responseNodeCount: 3,
        })
    })

    it('continues streaming when a middle generated AI block was deleted', () => {
        const result = streamNotebookAIResponseMarkdown(
            '# Notebook\n\nFirst paragraph\n\nThird paragraph still writing',
            3,
            'First paragraph\n\nSecond paragraph\n\nThird paragraph finished\n\nFourth paragraph still writing',
            3
        )

        expect(result).toEqual({
            markdown: '# Notebook\n\nFirst paragraph\n\nThird paragraph finished\n\nFourth paragraph still writing',
            responseNodeIndex: 3,
            responseNodeCount: 3,
        })
    })

    it('rebases the streamed AI response range after deleting an earlier generated block', () => {
        expect(
            rebaseNotebookAIResponseRange(
                '# Notebook\n\nFirst paragraph\n\nSecond paragraph\n\nThird paragraph still writing',
                '# Notebook\n\nSecond paragraph\n\nThird paragraph still writing',
                3,
                3
            )
        ).toEqual({ responseNodeIndex: 2, responseNodeCount: 2 })
    })

    it('replaces the active streamed block when the AI has only written one block so far', () => {
        const result = streamNotebookAIResponseMarkdown(
            '# Notebook\n\nFirst paragraph still writing',
            1,
            'First paragraph finished\n\nSecond paragraph still writing',
            1
        )

        expect(result).toEqual({
            markdown: '# Notebook\n\nFirst paragraph finished\n\nSecond paragraph still writing',
            responseNodeIndex: 2,
            responseNodeCount: 2,
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
            '# Notebook\n\n## Browsers in use\n\n<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"uONk"}} />\n\nThe chart shows browser usage.'
        )
    })

    it('defaults AI-inserted query components to results only', () => {
        const markdown = '# Notebook\n\nThinking...'

        expect(
            replaceMarkdown(
                markdown,
                1,
                '<Query query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}} />'
            )
        ).toEqual(
            '# Notebook\n\n<Query hideFilters query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}} />'
        )
    })

    it('defaults AI-inserted query components with edit props to results only', () => {
        const markdown = '# Notebook\n\nThinking...'

        expect(
            replaceMarkdown(
                markdown,
                1,
                '<Query edit={false} query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}} />'
            )
        ).toEqual(
            '# Notebook\n\n<Query hideFilters query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}} />'
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

    it('inserts another empty follow-up prompt when one is already open', () => {
        const markdown = '# Notebook\n\n<Prompt question="" />\n\nAnswer text'

        expect(insertNotebookAIFollowUpPromptAfterResponse(markdown, 2, '<Prompt question="" />')).toEqual(
            '# Notebook\n\n<Prompt question="" />\n\nAnswer text\n\n<Prompt question="" />'
        )
    })

    it('keeps the AI response anchored on the final list item before a follow-up prompt', () => {
        const markdown = '# Notebook\n\n- First\n- Second'

        expect(insertNotebookAIFollowUpPromptAfterResponse(markdown, 1, '<Prompt question="" />')).toEqual(
            '# Notebook\n\n- First\n- Second\n\n<Prompt question="" />'
        )
    })
})
