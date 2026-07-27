import { getNotebookAICaretPosition, getNotebookAIPromptCaretPosition } from './MarkdownNotebookV2Renderer'

describe('MarkdownNotebookV2Renderer', () => {
    it('places the AI caret at the end of a paragraph response', () => {
        expect(getNotebookAICaretPosition('# Notebook\n\nGenerated text', 1)).toEqual({
            nodeIndex: 1,
            offset: 'Generated text'.length,
        })
    })

    it('places the AI caret at the end of the last list item', () => {
        expect(getNotebookAICaretPosition('# Notebook\n\n- First\n- Second', 1)).toEqual({
            nodeIndex: 1,
            listItemIndex: 1,
            offset: 'Second'.length,
        })
    })

    it('places the AI caret at the end of code text', () => {
        expect(getNotebookAICaretPosition('# Notebook\n\n```sql\nSELECT 1\n```', 1)).toEqual({
            nodeIndex: 1,
            offset: 'SELECT 1'.length,
        })
    })

    it('clamps the AI caret to the last parsed block', () => {
        expect(getNotebookAICaretPosition('# Notebook\n\nGenerated text', 100)).toEqual({
            nodeIndex: 1,
            offset: 'Generated text'.length,
        })
    })

    it('places the AI caret before an open Ask AI prompt', () => {
        expect(getNotebookAIPromptCaretPosition('# Notebook\n\n<Prompt question="" />')).toEqual({
            nodeIndex: 0,
            offset: 'Notebook'.length,
        })
    })

    it('places the AI caret before the latest open Ask AI prompt', () => {
        expect(
            getNotebookAIPromptCaretPosition(
                '# Notebook\n\nFirst answer\n\n<Prompt question="" />\n\nSecond answer\n\n<Prompt question="" />'
            )
        ).toEqual({
            nodeIndex: 3,
            offset: 'Second answer'.length,
        })
    })

    it('does not anchor AI presence to a prompt with no previous line', () => {
        expect(getNotebookAIPromptCaretPosition('<Prompt question="" />')).toBeNull()
    })
})
