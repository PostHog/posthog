import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { SurveyQuestionType, SurveyType } from '~/types'

import { SurveyAPIEditor } from './SurveyAPIEditor'

jest.mock('lib/components/CodeSnippet', () => ({
    CodeSnippet: ({ children }: { children: string }) => <pre>{children}</pre>,
    Language: { JSON: 'json' },
}))

describe('SurveyAPIEditor', () => {
    it('includes appearance settings in the rendered payload', () => {
        render(
            <SurveyAPIEditor
                survey={
                    {
                        id: 'survey-id',
                        name: 'API survey',
                        description: '',
                        type: SurveyType.API,
                        linked_flag: null,
                        targeting_flag: null,
                        questions: [
                            {
                                id: 'question-id',
                                type: SurveyQuestionType.Open,
                                question: 'How did this go?',
                                description: '',
                            },
                        ],
                        conditions: null,
                        appearance: {
                            whiteLabel: true,
                        },
                        start_date: null,
                        end_date: null,
                    } as any
                }
            />
        )

        expect(screen.getByText(/"appearance": \{/)).toBeInTheDocument()
        expect(screen.getByText(/"whiteLabel": true/)).toBeInTheDocument()
    })
})
