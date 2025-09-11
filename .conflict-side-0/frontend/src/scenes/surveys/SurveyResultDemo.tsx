import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconGraph, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SurveyStatsSummaryWithData } from 'scenes/surveys/SurveyStatsSummary'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyQuestionType } from '~/types'

function SurveyResponsesByQuestionV2Demo(): JSX.Element {
    const { survey, surveyDemoData } = useValues(surveyLogic)

    return (
        <div className="flex flex-col gap-2">
            {survey.questions.map((question, i) => {
                if (!question.id || question.type === SurveyQuestionType.Link) {
                    return null
                }

                const processedResponses = surveyDemoData.demoProcessedResults[question.id]

                return (
                    <div key={question.id} className="flex flex-col gap-2">
                        <SurveyQuestionVisualization
                            question={question}
                            questionIndex={i}
                            demoData={processedResponses}
                        />
                        {i < survey.questions.length - 1 && <div className="border-b border-border" />}
                    </div>
                )
            })}
        </div>
    )
}

function DemoStatsSummary(): JSX.Element {
    const { surveyDemoData } = useValues(surveyLogic)

    return (
        <SurveyStatsSummaryWithData
            processedSurveyStats={surveyDemoData.demoStats}
            surveyRates={surveyDemoData.demoRates}
        />
    )
}

function DemoDataTable(): JSX.Element {
    const { survey, surveyDemoData } = useValues(surveyLogic)

    // Transform demo data into table format
    const tableData = useMemo(() => {
        return surveyDemoData.demoResults.map((row: any, index: number) => {
            const responseData: Record<string, any> = {}

            // Add question responses
            survey.questions.forEach((question, questionIndex) => {
                if (question.type !== SurveyQuestionType.Link && row[questionIndex] !== undefined) {
                    const value = row[questionIndex]
                    responseData[`question_${questionIndex}`] = Array.isArray(value) ? value.join(', ') : value
                }
            })

            // Add metadata columns - these are at the end of the row
            const personProps = row[row.length - 3] // Person properties JSON
            const distinctId = row[row.length - 2] // Distinct ID
            const timestamp = row[row.length - 1] // Timestamp

            let parsedPersonProps = {}
            try {
                parsedPersonProps = JSON.parse(personProps as string)
            } catch {
                // Keep empty object as fallback
            }

            return {
                id: index,
                timestamp,
                person: {
                    distinct_id: distinctId,
                    properties: parsedPersonProps,
                },
                url: 'https://app.example.com/dashboard',
                ...responseData,
            }
        })
    }, [surveyDemoData.demoResults, survey.questions])

    // Create table columns
    const columns = useMemo(() => {
        const cols: any[] = []

        // Add question columns first
        survey.questions.forEach((question, index) => {
            if (question.type !== SurveyQuestionType.Link) {
                cols.push({
                    title: `Q${index + 1}: ${question.question}`,
                    dataIndex: `question_${index}`,
                    key: `question_${index}`,
                    render: (value: string) => (
                        <span className="max-w-xs truncate inline-block" title={value}>
                            {value || '-'}
                        </span>
                    ),
                    width: 200,
                })
            }
        })

        // Then add metadata columns
        cols.push(
            {
                title: '',
                dataIndex: 'timestamp',
                key: 'timestamp',
                render: (timestamp: string) => <TZLabel time={timestamp} />,
                width: 150,
            },
            {
                title: 'Person',
                dataIndex: 'person',
                key: 'person',
                render: (person: { distinct_id: string; properties: Record<string, any> }) => (
                    <PersonDisplay person={person} withIcon={true} noEllipsis={false} isCentered={false} />
                ),
                width: 160,
            },
            {
                title: 'URL',
                dataIndex: 'url',
                key: 'url',
                render: (url: string) => (
                    <span className="text-link truncate max-w-48 inline-block" title={url}>
                        {url}
                    </span>
                ),
                width: 200,
            }
        )

        return cols
    }, [survey.questions])

    return (
        <div className="survey-table-results">
            <LemonBanner type="info" className="mb-4">
                <div className="flex items-center gap-2">
                    <IconInfo className="text-muted" />
                    <span>This table shows example data structure. Launch your survey to see real responses here.</span>
                </div>
            </LemonBanner>
            <LemonTable dataSource={tableData} columns={columns} rowKey="id" size="small" />
        </div>
    )
}

export function SurveyResultDemo(): JSX.Element {
    return (
        <div className="deprecated-space-y-4">
            <LemonBanner type="info">
                <div className="flex items-center gap-2">
                    <IconInfo className="text-muted" />
                    <div>
                        <strong>Demo Results</strong> - This shows how your survey results will look with sample data.
                        Launch your survey to start collecting real responses.
                    </div>
                </div>
            </LemonBanner>

            <DemoStatsSummary />

            <SurveyResponsesByQuestionV2Demo />

            <LemonButton
                type="primary"
                data-attr="survey-results-explore-demo"
                icon={<IconGraph />}
                className="max-w-40"
                tooltip="This will be available after launching your survey"
                disabledReason="Demo mode - launch survey to explore real results"
            >
                Explore results
            </LemonButton>

            <DemoDataTable />
        </div>
    )
}
