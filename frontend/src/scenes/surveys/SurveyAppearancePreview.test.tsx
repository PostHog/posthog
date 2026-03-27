import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'

import { SurveyPosition, SurveyQuestionType, SurveyType } from '~/types'

import { SurveyAppearancePreview } from './SurveyAppearancePreview'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

const mockRenderSurveysPreview = jest.mocked(renderSurveysPreview)
type RenderSurveysPreviewArgs = Parameters<typeof renderSurveysPreview>[0]

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
    })

    it('renders previews inside a bounded container and passes the same container to the renderer', () => {
        mockRenderSurveysPreview.mockImplementation(({ parentElement, positionStyles }: RenderSurveysPreviewArgs) => {
            const previewElement = document.createElement('div')
            Object.assign(previewElement.style, positionStyles)
            parentElement.appendChild(previewElement)
        })

        const { container } = render(<SurveyAppearancePreview survey={survey} previewPageIndex={0} />)
        const previewRoot = container.firstChild as HTMLDivElement

        expect(previewRoot).toHaveClass('flex', 'w-full', 'min-w-0', 'justify-center', 'overflow-hidden')

        expect(mockRenderSurveysPreview).toHaveBeenCalledWith(
            expect.objectContaining({
                parentElement: previewRoot,
                positionStyles: expect.objectContaining({
                    width: '100%',
                    maxWidth: 'min(var(--ph-survey-max-width), 100%)',
                    minWidth: '0',
                    boxSizing: 'border-box',
                }),
            })
        )

        const renderedPreview = previewRoot.firstChild as HTMLDivElement
        expect(renderedPreview.style.width).toBe('100%')
        expect(renderedPreview.style.maxWidth).toBe('min(var(--ph-survey-max-width), 100%)')
        expect(renderedPreview.style.minWidth).toBe('0')
        expect(renderedPreview.style.boxSizing).toBe('border-box')
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
