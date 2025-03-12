import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { Survey, SurveyQuestion } from '~/types'

import { createAnswerFilterHogQLExpression, getResponseFieldCondition } from './utils'

interface SurveySQLHelperProps {
    isOpen: boolean
    onClose: () => void
}

export function SurveySQLHelper({ isOpen, onClose }: SurveySQLHelperProps): JSX.Element {
    const { survey, answerFilters } = useValues(surveyLogic)

    const filterConditions = createAnswerFilterHogQLExpression(answerFilters, survey as Survey)

    const generateSingleQuestionQuery = (question: SurveyQuestion, index: number): string => {
        return `SELECT
    distinct_id,
    ${getResponseFieldCondition(index, question.id)} AS "${question.question}",
    timestamp
FROM
    events
WHERE
    event = 'survey sent'
    AND properties.$survey_id = '${survey.id}'${filterConditions ? '\n' + filterConditions : ''}
ORDER BY
    timestamp DESC
LIMIT
    100`
    }

    const generateFullSurveyQuery = (): string => {
        const questionSelects = survey.questions
            .map((question: SurveyQuestion, index: number) => {
                return `    ${getResponseFieldCondition(index, question.id)} AS "${question.question}"`
            })
            .join(',\n')

        return `SELECT
    distinct_id,
${questionSelects},
    timestamp
FROM
    events
WHERE
    event = 'survey sent'
    AND properties.$survey_id = '${survey.id}'${filterConditions ? '\n' + filterConditions : ''}
ORDER BY
    timestamp DESC
LIMIT
    100`
    }

    // Function to open query in a new insight
    const openInInsight = (query: string): void => {
        const insightQuery = {
            kind: NodeKind.DataTableNode,
            full: true,
            source: {
                kind: NodeKind.HogQLQuery,
                query: query,
            },
        }
        router.actions.push(urls.insightNew({ query: insightQuery }))
    }

    // Check if any filters are applied
    const hasAppliedFilters = (): boolean => {
        return answerFilters && answerFilters.some((f) => f.value && (!Array.isArray(f.value) || f.value.length > 0))
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="SQL Query Helper"
            description={
                <div className="flex flex-col gap-1 text-sm text-muted">
                    <p>
                        <b>Important:</b> Since March 7, 2024, survey responses are stored using question IDs ([UUID](https://en.wikipedia.org/wiki/Universally_unique_identifier)) instead of
                        indexes. The queries below handle both formats using the <code>coalesce</code> function.
                    </p>
                    {hasAppliedFilters() && (
                        <p>
                            <b>Note:</b> Your answer filters from the UI have been included in the SQL queries.
                        </p>
                    )}
                </div>
            }
            width={800}
        >
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <h4>Full Survey Query</h4>
                    <p className="text-sm text-muted">Returns all questions for this survey.</p>
                    <CodeSnippet
                        language={Language.SQL}
                        compact
                        actions={
                            <LemonButton
                                icon={<IconOpenInNew />}
                                size="small"
                                onClick={() => openInInsight(generateFullSurveyQuery())}
                                tooltip="Open as new insight"
                                noPadding
                            />
                        }
                    >
                        {generateFullSurveyQuery()}
                    </CodeSnippet>
                </div>

                <LemonDivider />

                <div className="flex flex-col gap-2">
                    <h4>Individual Question Queries</h4>
                    <p className="text-sm text-muted">Returns responses for individual questions.</p>

                    <div className="flex flex-col gap-1">
                        {survey.questions.map((question: SurveyQuestion, index: number) => (
                            <div key={question.id || index} className="flex flex-col gap-2">
                                <h5>{question.question}</h5>
                                <CodeSnippet
                                    language={Language.SQL}
                                    compact
                                    actions={
                                        <LemonButton
                                            icon={<IconOpenInNew />}
                                            size="small"
                                            onClick={() => openInInsight(generateSingleQuestionQuery(question, index))}
                                            tooltip="Open as new insight"
                                            noPadding
                                        />
                                    }
                                >
                                    {generateSingleQuestionQuery(question, index)}
                                </CodeSnippet>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
