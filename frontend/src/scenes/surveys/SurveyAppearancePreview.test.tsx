import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import type { CSSProperties } from 'react'

import { SurveyPosition, SurveyQuestionType, SurveyType } from '~/types'

import { SurveyAppearancePreview } from './SurveyAppearancePreview'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderSurveysPreview: jest.fn(),
}))

const mockRenderSurveysPreview = jest.mocked(renderSurveysPreview)

interface RenderSurveysPreviewArgs {
    parentElement: HTMLDivElement
    positionStyles?: CSSProperties
}

describe('SurveyAppearancePreview', () => {
    const survey = {
        id: 'survey-preview',
        name: 'Preview survey',
        description: '',
        type: SurveyType.Popover,
        questions: [
            {
                id: 'question-1',
                type: SurveyQuestionType.Open,
                question: 'How did we do?',
            },
        ],
        appearance: {
            position: SurveyPosition.Right,
            maxWidth: '640px',
        },
    } as any

    beforeEach(() => {
        mockRenderSurveysPreview.mockClear()
        // jsdom has no CSS.supports, which color sanitizing calls.
        global.CSS = { supports: () => false } as unknown as typeof CSS
    })

    it('renders previews inside a bounded container and passes the same container to the renderer', () => {
        mockRenderSurveysPreview.mockImplementation(({ parentElement, positionStyles }: RenderSurveysPreviewArgs) => {
            const previewElement = document.createElement('div')
            Object.assign(previewElement.style, positionStyles)
            parentElement.appendChild(previewElement)
        })

        const { container } = render(<SurveyAppearancePreview survey={survey} previewPageIndex={0} />)
        const previewRoot = container.firstChild as HTMLDivElement

        expect(previewRoot).toHaveClass('flex', 'w-full', 'min-w-0', 'justify-center')

        expect(mockRenderSurveysPreview).toHaveBeenCalledWith(
            expect.objectContaining({
                parentElement: previewRoot,
                positionStyles: expect.objectContaining({
                    width: 'var(--ph-survey-max-width)',
                    maxWidth: '100%',
                    minWidth: 'min(300px, 100%)',
                    boxSizing: 'border-box',
                }),
            })
        )

        const renderedPreview = previewRoot.firstChild as HTMLDivElement
        expect(renderedPreview.style.maxWidth).toBe('100%')
        expect(renderedPreview.style.minWidth).toBe('min(300px, 100%)')
        expect(renderedPreview.style.boxSizing).toBe('border-box')
    })

    // posthog-js spreads the appearance over its defaults, so a color key that is present but unset erases the
    // default, and the preview draws a transparent survey.
    it.each([
        ['no colors stored', {}, undefined],
        ['an empty color', { backgroundColor: '' }, undefined],
        ['a set color', { backgroundColor: '#ff0000' }, '#ff0000'],
    ])('hands the renderer a background color only when one is set (%s)', (_name, colors, expected) => {
        render(
            <SurveyAppearancePreview
                survey={{ ...survey, appearance: { ...survey.appearance, ...colors } }}
                previewPageIndex={0}
            />
        )

        const { appearance } = mockRenderSurveysPreview.mock.calls[0][0].survey
        expect(Object.prototype.hasOwnProperty.call(appearance, 'backgroundColor')).toBe(expected !== undefined)
        expect(appearance.backgroundColor).toBe(expected)
        expect(Object.values(appearance)).not.toContain(undefined)
    })

    it('uses explicit position styles when provided', () => {
        const customPositionStyles = { width: '75%', maxWidth: '420px' }

        render(<SurveyAppearancePreview survey={survey} previewPageIndex={0} positionStyles={customPositionStyles} />)

        expect(mockRenderSurveysPreview).toHaveBeenCalledWith(
            expect.objectContaining({
                positionStyles: customPositionStyles,
            })
        )
    })
})
