import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyWithTranslatedContent } from 'scenes/surveys/surveyTranslationUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import { HostedSurveyCanvas } from './HostedSurveyCanvas'

const baseSurvey: Survey = {
    id: 'test-survey',
    name: 'Test survey',
    description: '',
    type: SurveyType.ExternalSurvey,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    questions: [{ type: SurveyQuestionType.Open, question: 'What do you think?', description: '' }],
    conditions: null,
    appearance: {
        displayIntroScreen: true,
        introScreenHeader: 'Welcome',
        displayThankYouMessage: true,
        thankYouMessageHeader: 'Thanks',
    },
    translations: { fr: { introScreenHeader: 'Bienvenue', thankYouMessageHeader: 'Merci' } },
    created_at: '2026-01-01T00:00:00.000Z',
    created_by: null,
    start_date: null,
    end_date: null,
    archived: false,
    targeting_flag_filters: undefined,
    responses_limit: null,
    schedule: SurveySchedule.Once,
    user_access_level: AccessControlLevel.Editor,
}

describe('HostedSurveyCanvas', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/test-survey/': () => [200, baseSurvey],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => [200, {}],
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        ['intro', 'intro', 'Intro header', 'introScreenHeader', 'thankYouMessageHeader', 'Thanks'],
        ['confirmation', 'confirmation', 'Thank you header', 'thankYouMessageHeader', 'introScreenHeader', 'Welcome'],
    ] as const)(
        'editing the %s while a translation is shown keeps the untouched base text',
        (_name, pageKind, ariaLabel, editedField, untouchedField, untouchedBaseValue) => {
            const logic = surveyLogic({ id: baseSurvey.id })
            logic.mount()
            logic.actions.loadSurveySuccess(baseSurvey)

            render(
                <BindLogic logic={surveyLogic} props={{ id: baseSurvey.id }}>
                    <HostedSurveyCanvas
                        survey={getSurveyWithTranslatedContent(baseSurvey, 'fr')}
                        activePageIndex={pageKind === 'intro' ? -1 : 1}
                        pageKind={pageKind}
                        viewport="desktop"
                    />
                </BindLogic>
            )
            fireEvent.click(screen.getByLabelText(ariaLabel))
            fireEvent.change(screen.getByLabelText(ariaLabel), { target: { value: 'Edited' } })
            fireEvent.blur(screen.getByLabelText(ariaLabel))

            expect(logic.values.survey.appearance?.[editedField]).toBe('Edited')
            expect(logic.values.survey.appearance?.[untouchedField]).toBe(untouchedBaseValue)
        }
    )

    it('keeps a typed intro description editable when the content type was unset', () => {
        const survey: Survey = {
            ...baseSurvey,
            appearance: {
                ...baseSurvey.appearance,
                introScreenDescription: '',
                introScreenDescriptionContentType: undefined,
            },
        }
        const logic = surveyLogic({ id: survey.id })
        logic.mount()
        logic.actions.loadSurveySuccess(survey)
        const renderCanvas = (): JSX.Element => (
            <BindLogic logic={surveyLogic} props={{ id: survey.id }}>
                <HostedSurveyCanvas
                    survey={logic.values.survey as Survey}
                    activePageIndex={-1}
                    pageKind="intro"
                    viewport="desktop"
                />
            </BindLogic>
        )
        const { rerender } = render(renderCanvas())

        for (const text of ['First draft', 'Second draft']) {
            fireEvent.click(screen.getByLabelText('Intro description'))
            fireEvent.change(screen.getByLabelText('Intro description'), { target: { value: text } })
            fireEvent.blur(screen.getByLabelText('Intro description'))
            rerender(renderCanvas())
        }

        expect(logic.values.survey.appearance?.introScreenDescription).toBe('Second draft')
        expect(logic.values.survey.appearance?.introScreenDescriptionContentType).toBe('text')
    })

    it.each([
        ['an unset content type', undefined, true],
        ['an html content type', 'html', true],
        ['a text content type', 'text', false],
    ] as const)('renders the intro description as %s', (_name, contentType, rendersHtml) => {
        const survey: Survey = {
            ...baseSurvey,
            appearance: {
                ...baseSurvey.appearance,
                introScreenDescription: '<b>Takes a minute</b>',
                introScreenDescriptionContentType: contentType,
            },
        }
        const logic = surveyLogic({ id: survey.id })
        logic.mount()
        logic.actions.loadSurveySuccess(survey)

        render(
            <BindLogic logic={surveyLogic} props={{ id: survey.id }}>
                <HostedSurveyCanvas survey={survey} activePageIndex={-1} pageKind="intro" viewport="desktop" />
            </BindLogic>
        )

        expect(!!screen.queryByText('Takes a minute')).toBe(rendersHtml)
        expect(!!screen.queryByLabelText('Intro description')).toBe(!rendersHtml)
    })
})
