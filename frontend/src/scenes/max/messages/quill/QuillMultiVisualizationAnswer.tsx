import { IconExpand } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { NotQuill, QuillAssistantMarkdown, quillCardBorderClass } from 'products/posthog_ai/frontend/api/primitives'

import type { MultiVisualizationAnswerProps } from '../MultiVisualizationAnswer'
import { useMultiVisualizationInsights } from '../multiVisualizationInsights'
import { openMultiVisualizationModal } from '../MultiVisualizationModal'
import { MultiVisualizationMosaic } from '../MultiVisualizationMosaic'

export function QuillMultiVisualizationAnswer({ message, className }: MultiVisualizationAnswerProps): JSX.Element {
    const insights = useMultiVisualizationInsights(message.visualizations)
    return (
        <Card size="sm" className={cn('w-full max-w-full', quillCardBorderClass(), className)}>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
                <CardTitle>{pluralize(message.visualizations.length, 'insight')} analyzed</CardTitle>
                {message.visualizations.length > 1 && (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openMultiVisualizationModal(insights)}
                        tooltip="View all insights in detail"
                    >
                        <IconExpand />
                        Expand
                    </Button>
                )}
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
                <NotQuill>
                    <MultiVisualizationMosaic insights={insights} />
                </NotQuill>
                {message.commentary && (
                    <QuillAssistantMarkdown content={message.commentary} id="multi-viz-commentary" />
                )}
            </CardContent>
        </Card>
    )
}
