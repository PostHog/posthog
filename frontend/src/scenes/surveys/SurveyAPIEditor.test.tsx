import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { SurveyType } from '~/types'

import { type NewSurvey, NEW_SURVEY } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'

jest.mock('lib/components/CodeSnippet', () => ({
    CodeSnippet: ({ children }: { children: string }) => <pre>{children}</pre>,
    Language: { JSON: 'json' },
}))

describe('SurveyAPIEditor', () => {
    it('includes appearance settings in the rendered payload', () => {
        const survey = {
            ...NEW_SURVEY,
            id: 'survey-id',
            name: 'API survey',
            type: SurveyType.API,
            questions: [
                {
                    ...NEW_SURVEY.questions[0],
                    id: 'question-id',
                    question: 'How did this go?',
                },
            ],
            appearance: {
                ...NEW_SURVEY.appearance,
                whiteLabel: true,
            },
        } satisfies NewSurvey

        render(
            <SurveyAPIEditor survey={survey} />
        )

        expect(screen.getByText(/"appearance": \{/)).toBeInTheDocument()
        expect(screen.getByText(/"whiteLabel": true/)).toBeInTheDocument()
    })
})
