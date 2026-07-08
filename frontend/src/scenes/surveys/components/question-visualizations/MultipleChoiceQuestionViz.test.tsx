import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { dimensions, ensureJsdom } from '@posthog/quill-charts/testing'

import { MultipleChoiceQuestionViz } from 'scenes/surveys/components/question-visualizations/MultipleChoiceQuestionViz'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    ChoiceQuestionResponseData,
    MultipleSurveyQuestion,
    PropertyFilterType,
    PropertyOperator,
    SurveyQuestionType,
} from '~/types'

const QUESTION: MultipleSurveyQuestion = {
    id: 'q1',
    type: SurveyQuestionType.MultipleChoice,
    question: 'Which features do you use?',
    choices: ['Feature A', 'Feature B'],
}

const RESPONSE_DATA: ChoiceQuestionResponseData[] = [
    { label: 'Feature A', value: 3, isPredefined: true },
    { label: 'Feature B', value: 2, isPredefined: true },
]

describe('MultipleChoiceQuestionViz double-click filtering', () => {
    let logic: ReturnType<typeof surveyLogic.build>

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
        // answerFilters is a persisted reducer and setAnswerFilters writes ?answerFilters=… to the
        // URL — clear both so a previous test's applied filter doesn't leak into the next mount.
        localStorage.clear()
        router.actions.push('/surveys/test-survey')
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/test-survey/': () => [
                    200,
                    {
                        id: 'test-survey',
                        name: 'Test survey',
                        type: 'popover',
                        questions: [QUESTION],
                        start_date: '2026-01-01T00:00:00Z',
                        end_date: null,
                        archived: false,
                        appearance: {},
                        conditions: null,
                        created_at: '2026-01-01T00:00:00Z',
                    },
                ],
                '/api/projects/:team/surveys/test-survey/archived-response-uuids/': () => [200, []],
                '/api/projects/:team/surveys/responses_count/': () => [200, {}],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        })
        logic = surveyLogic({ id: 'test-survey' })
        logic.mount()
    })

    function renderViz(): HTMLElement {
        render(
            <BindLogic logic={surveyLogic} props={{ id: 'test-survey' }}>
                <MultipleChoiceQuestionViz
                    question={QUESTION}
                    questionIndex={0}
                    responseData={RESPONSE_DATA}
                    totalResponses={5}
                />
            </BindLogic>
        )
        const chart = document.querySelector('[data-attr="survey-multiple-choice"]')
        if (!(chart instanceof HTMLElement)) {
            throw new Error('chart wrapper not rendered')
        }
        return chart
    }

    // Horizontal chart: bands run down the y axis, one row per choice (sorted by value, so
    // row 0 is "Feature A"). Quill resolves clicks through the last hover position.
    function clickRow(chart: HTMLElement, rowIndex: number): void {
        const rowStep = dimensions.plotHeight / RESPONSE_DATA.length
        fireEvent.mouseMove(chart, {
            clientX: dimensions.plotLeft + dimensions.plotWidth * 0.2,
            clientY: dimensions.plotTop + rowStep * (rowIndex + 0.5),
        })
        fireEvent.click(chart)
    }

    it('arms on the first click without applying a filter', () => {
        const chart = renderViz()

        clickRow(chart, 0)

        expect(screen.getByText('Click "Feature A" again to filter by this choice.')).toBeTruthy()
        expect(logic.values.answerFilters).toEqual([])
    })

    it('applies the answer filter on the second click of a double-click', () => {
        const chart = renderViz()

        clickRow(chart, 0)
        clickRow(chart, 0)

        expect(logic.values.answerFilters).toEqual([
            {
                key: '$survey_response_q1',
                type: PropertyFilterType.Event,
                operator: PropertyOperator.IContains,
                value: 'Feature A',
            },
        ])
        expect(screen.getByText(/Showing only "Feature A" responses/)).toBeTruthy()
    })

    it('clears the armed state after the timeout without applying a filter', () => {
        jest.useFakeTimers()
        const chart = renderViz()

        clickRow(chart, 0)
        expect(screen.getByText('Click "Feature A" again to filter by this choice.')).toBeTruthy()

        act(() => {
            jest.advanceTimersByTime(2600)
        })

        expect(screen.getByText('Double-click an option to filter by that choice.')).toBeTruthy()
        expect(logic.values.answerFilters).toEqual([])
    })
})
