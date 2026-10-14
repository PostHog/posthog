import { Survey, SurveyQuestion, SurveyQuestionType } from '~/types'

import { NewSurvey } from './constants'

const UNSAVED_SURVEY_ID = '<survey id>'
const UNSAVED_QUESTION_ID = '<question id>'
const QUESTION_COMMENT_MAX_LENGTH = 60
const IDENTIFIER = /^[A-Za-z_$][\w$]*$/

const quote = (value: string): string =>
    `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n')}'`

const propertyKey = (key: string): string => (IDENTIFIER.test(key) ? key : quote(key))

const firstChoice = (question: SurveyQuestion, fallback: string): string =>
    quote(('choices' in question && question.choices[0]) || fallback)

const ANSWER_PLACEHOLDERS: Record<SurveyQuestionType, (question: SurveyQuestion) => string> = {
    [SurveyQuestionType.Open]: () => quote('Your answer'),
    [SurveyQuestionType.Link]: () => quote('Your answer'),
    [SurveyQuestionType.Rating]: (question) => quote(String('scale' in question ? question.scale : 5)),
    [SurveyQuestionType.SingleChoice]: (question) => firstChoice(question, 'Your answer'),
    [SurveyQuestionType.MultipleChoice]: (question) => `[${firstChoice(question, 'Option 1')}]`,
}

function questionComment(text: string): string {
    const singleLine = text.replace(/\s+/g, ' ').trim()
    return singleLine.length > QUESTION_COMMENT_MAX_LENGTH
        ? `${singleLine.slice(0, QUESTION_COMMENT_MAX_LENGTH).trimEnd()}…`
        : singleLine
}

function responseLines(question: SurveyQuestion): string[] {
    const key = propertyKey(`$survey_response_${question.id ?? UNSAVED_QUESTION_ID}`)
    return [
        `    // ${questionComment(question.question)}`,
        `    ${key}: ${ANSWER_PLACEHOLDERS[question.type](question)},`,
    ]
}

export function buildApiSurveySnippet(survey: Survey | NewSurvey): string {
    const id = survey.id && survey.id !== 'new' ? survey.id : UNSAVED_SURVEY_ID
    const quotedId = quote(id)
    const respondedKey = survey.current_iteration
        ? `$survey_responded/${id}/${survey.current_iteration}`
        : `$survey_responded/${id}`

    return [
        'posthog.getActiveMatchingSurveys((surveys) => {',
        `    const survey = surveys.find((s) => s.id === ${quotedId})`,
        '    if (!survey) return',
        '    // Render your own UI, then:',
        `    posthog.capture('survey shown', { $survey_id: ${quotedId} })`,
        '})',
        '',
        '// When the user submits',
        "posthog.capture('survey sent', {",
        `    $survey_id: ${quotedId},`,
        '    $survey_submission_id: crypto.randomUUID(),',
        '    $survey_completed: true,',
        ...survey.questions.flatMap(responseLines),
        `    $set: { ${quote(respondedKey)}: true },`,
        '})',
        '',
        '// When the user closes the survey without answering',
        `posthog.capture('survey dismissed', { $survey_id: ${quotedId} })`,
    ].join('\n')
}
