import { Heading, Text } from '@posthog/quill'

import { WarehouseQuestionCard } from './WarehouseQuestionCard'
import { WAREHOUSE_QUESTIONS, WAREHOUSE_QUESTIONS_SECTION_ID } from './warehouseQuestionsContent'

export function WarehouseQuestions(): JSX.Element {
    return (
        <section
            id={WAREHOUSE_QUESTIONS_SECTION_ID}
            aria-labelledby="warehouse-questions-heading"
            className="flex scroll-mt-4 flex-col gap-3"
        >
            <div className="flex flex-col gap-1">
                <Heading render={<h2 id="warehouse-questions-heading" />} size="base" className="m-0">
                    Start with a question
                </Heading>
                <Text size="sm" variant="muted">
                    Your warehouse already holds all your PostHog data. Add an external source and you can answer
                    questions neither could answer alone.
                </Text>
            </div>
            <div className="grid gap-4 @2xl/warehouse-home:grid-cols-2 @5xl/warehouse-home:grid-cols-3">
                {WAREHOUSE_QUESTIONS.map((question) => (
                    <WarehouseQuestionCard key={question.id} question={question} />
                ))}
            </div>
        </section>
    )
}
