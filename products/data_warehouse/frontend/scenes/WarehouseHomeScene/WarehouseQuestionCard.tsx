import posthog from 'posthog-js'

import { Button, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import {
    WAREHOUSE_QUESTION_PROMPT_SUFFIX,
    WAREHOUSE_TOOL_CATEGORIES,
    WarehouseQuestion,
} from './warehouseQuestionsContent'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseQuestionCard({ question }: { question: WarehouseQuestion }): JSX.Element {
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>{question.question}</CardTitle>
                <Text size="xs" variant="muted">
                    PostHog {question.posthogData.toLowerCase()} +{' '}
                    {question.toolCategories.map((category) => WAREHOUSE_TOOL_CATEGORIES[category].label).join(' + ')}
                </Text>
                <CardDescription>{question.description}</CardDescription>
            </CardHeader>
            <CardContent>
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                    {question.toolCategories.map((category) => (
                        <li key={category}>
                            <Text size="xs" variant="muted">
                                <Text size="xs" weight="medium" render={<span />}>
                                    {WAREHOUSE_TOOL_CATEGORIES[category].pluralLabel}:
                                </Text>{' '}
                                {WAREHOUSE_TOOL_CATEGORIES[category].tools.join(', ')}
                            </Text>
                        </li>
                    ))}
                </ul>
            </CardContent>
            <CardFooter className="mt-auto flex-wrap gap-2">
                <Button
                    size="sm"
                    variant="primary"
                    nativeButton={false}
                    render={
                        <LinkPrimitive
                            to={urls.ai(undefined, `${question.aiPrompt} ${WAREHOUSE_QUESTION_PROMPT_SUFFIX}`)}
                        />
                    }
                    data-attr={`warehouse-question-ask-ai-${question.id}`}
                    onClick={() =>
                        posthog.capture('warehouse question clicked', { question: question.id, target: 'ask_ai' })
                    }
                >
                    Ask PostHog AI
                </Button>
                <Button
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={question.guideUrl} target="_blank" />}
                    data-attr={`warehouse-question-guide-${question.id}`}
                    onClick={() =>
                        posthog.capture('warehouse question clicked', { question: question.id, target: 'guide' })
                    }
                >
                    Read the guide
                </Button>
            </CardFooter>
        </Card>
    )
}
