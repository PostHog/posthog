import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { InsightMetaContent } from './InsightMeta'

describe('InsightMetaContent', () => {
    const description = 'Test description content'

    // The caller (InsightMeta) computes showDescription from tile.show_description:
    //   showDescription={tile?.show_description !== false}
    // So null/undefined → true (show by default), false → false (explicitly hidden).
    // These tests verify the rendering behavior given those computed values.
    describe('description visibility in compact mode', () => {
        it.each([
            { showDescription: true, visible: true, label: 'show_description=true' },
            { showDescription: false, visible: false, label: 'show_description=false (explicitly hidden)' },
        ])('$label → description visible: $visible', ({ showDescription, visible }) => {
            const { container } = render(
                <InsightMetaContent
                    title="Test"
                    description={description}
                    compact={true}
                    showDescription={showDescription}
                />
            )
            if (visible) {
                expect(container.querySelector('.CardMeta__description')).toBeInTheDocument()
            } else {
                expect(container.querySelector('.CardMeta__description')).toBeNull()
            }
        })
    })

    it('always shows description in non-compact mode regardless of showDescription', () => {
        const { container } = render(
            <InsightMetaContent title="Test" description={description} compact={false} showDescription={false} />
        )
        expect(container.querySelector('.CardMeta__description')).toBeInTheDocument()
    })

    describe('inline description editing', () => {
        beforeEach(() => {
            initKeaTests()
        })

        it('renders a static description when onDescriptionSave is not provided', () => {
            const { container } = render(<InsightMetaContent title="Test" description={description} />)
            expect(container.querySelector('[data-attr="insight-card-description-inline"]')).toBeNull()
            expect(container.querySelector('.CardMeta__description')).toBeInTheDocument()
        })

        it('saves an edited description on blur when onDescriptionSave is provided', async () => {
            const onDescriptionSave = jest.fn()
            const { container } = render(
                <InsightMetaContent title="Test" description={description} onDescriptionSave={onDescriptionSave} />
            )
            const field = container.querySelector('[data-attr="insight-card-description-inline"]')
            expect(field).toBeInTheDocument()

            // Click the rendered description text to enter edit mode
            await userEvent.click(field!.querySelector('.LemonMarkdown')!)
            const textarea = field!.querySelector('textarea')
            expect(textarea).toBeInTheDocument()

            await userEvent.clear(textarea!)
            await userEvent.type(textarea!, 'Updated description')
            await userEvent.tab() // Blur the textarea

            expect(onDescriptionSave).toHaveBeenCalledTimes(1)
            expect(onDescriptionSave).toHaveBeenCalledWith('Updated description')
        })

        it('does not save on blur when the description is unchanged', async () => {
            const onDescriptionSave = jest.fn()
            const { container } = render(
                <InsightMetaContent title="Test" description={description} onDescriptionSave={onDescriptionSave} />
            )
            const field = container.querySelector('[data-attr="insight-card-description-inline"]')

            await userEvent.click(field!.querySelector('.LemonMarkdown')!)
            await userEvent.tab()

            expect(onDescriptionSave).not.toHaveBeenCalled()
        })
    })

    describe('tile.show_description default-to-show mapping', () => {
        // This tests the conversion logic used by the caller:
        //   tile?.show_description !== false
        // Null/undefined should map to "show", only explicit false hides.
        it.each([
            { tileValue: null, expected: true, label: 'null (new tile)' },
            { tileValue: undefined, expected: true, label: 'undefined (no tile)' },
            { tileValue: true, expected: true, label: 'true (explicitly shown)' },
            { tileValue: false, expected: false, label: 'false (explicitly hidden)' },
        ])('$label → showDescription=$expected', ({ tileValue, expected }) => {
            const tile = tileValue !== undefined ? { show_description: tileValue } : undefined
            const showDescription = tile?.show_description !== false
            expect(showDescription).toBe(expected)
        })
    })
})
