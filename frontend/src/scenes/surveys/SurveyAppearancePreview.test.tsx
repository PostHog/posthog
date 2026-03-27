import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'

import { SurveyPosition, SurveyQuestionType, SurveyType } from '~/types'

import { SurveyAppearancePreview } from './SurveyAppearancePreview'

const mockRenderSurveysPreview = jest.mocked(renderSurveysPreview)

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

    it('caps the preview width to the container by default', () => {
        render(<SurveyAppearancePreview survey={survey} previewPageIndex={0} />)

        expect(mockRenderSurveysPreview).toHaveBeenCalledWith(
            expect.objectContaining({
                positionStyles: expect.objectContaining({
                    width: '100%',
                    maxWidth: 'min(var(--ph-survey-max-width), 100%)',
                    minWidth: '0',
                    boxSizing: 'border-box',
                }),
            })
        )
    })
})
