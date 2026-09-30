import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { urls } from 'scenes/urls'

import { Survey, SurveyQuestion } from '~/types'

import { buildSurveyResponseSQLQuery } from './utils'

interface SurveySQLHelperProps {
    isOpen: boolean
    onClose: () => void
}

export function SurveySQLHelper({ isOpen, onClose }: SurveySQLHelperProps): JSX.Element {
    const { survey, answerFilters, timestampFilter, archivedResponsesFilter } = useValues(surveyLogic)
    const queryFilters = { answerFilters, timestampFilter, archivedResponsesFilter }
    const fullSurveyQuery = buildSurveyResponseSQLQuery(survey as Survey, queryFilters)

    // Function to open query in a new insight
    const openInInsight = (query: string): void => {
        router.actions.push(urls.sqlEditor({ query: query }))
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="SQL Query Helper"
            description={
                <div className="flex flex-col gap-1 text-sm text-muted">
                    <p>
                        <b>Important:</b> Since March 7, 2025, survey responses are stored using question IDs
                        ([UUID](https://en.wikipedia.org/wiki/Universally_unique_identifier)) instead of indexes. The
                        queries below merge captured answers from both formats into one row per submission.
                    </p>
                    <p>
                        <b>Note:</b> These queries only include response filters set on the table. Additional property
                        filters like cohorts, user properties, etc. are not included.
                    </p>
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
                                onClick={() => openInInsight(fullSurveyQuery)}
                                tooltip="Open as new insight"
                                noPadding
                            />
                        }
                    >
                        {fullSurveyQuery}
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
                                            onClick={() =>
                                                openInInsight(
                                                    buildSurveyResponseSQLQuery(survey as Survey, queryFilters, index)
                                                )
                                            }
                                            tooltip="Open as new insight"
                                            noPadding
                                        />
                                    }
                                >
                                    {buildSurveyResponseSQLQuery(survey as Survey, queryFilters, index)}
                                </CodeSnippet>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
