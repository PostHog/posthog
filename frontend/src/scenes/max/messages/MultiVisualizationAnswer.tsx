import clsx from 'clsx'

import { IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { MultiVisualizationMessage } from '~/queries/schema/schema-assistant-messages'

import { MarkdownMessage, useQuillThread } from 'products/posthog_ai/frontend/api/primitives'

import { useMultiVisualizationInsights } from './multiVisualizationInsights'
import { openMultiVisualizationModal } from './MultiVisualizationModal'
import { MultiVisualizationMosaic } from './MultiVisualizationMosaic'
import { QuillMultiVisualizationAnswer } from './quill/QuillMultiVisualizationAnswer'

export interface MultiVisualizationAnswerProps {
    message: MultiVisualizationMessage
    className?: string
}

export function MultiVisualizationAnswer(props: MultiVisualizationAnswerProps): JSX.Element | null {
    const quill = useQuillThread()
    if (props.message.visualizations.length === 0) {
        return null
    }
    return quill ? <QuillMultiVisualizationAnswer {...props} /> : <LemonMultiVisualizationAnswer {...props} />
}

function LemonMultiVisualizationAnswer({ message, className }: MultiVisualizationAnswerProps): JSX.Element {
    const insights = useMultiVisualizationInsights(message.visualizations)
    return (
        <div className={clsx('flex flex-col gap-px w-full break-words', className)}>
            <div className="max-w-full border py-3 px-4 rounded-lg bg-surface-primary">
                <div className="space-y-2">
                    <div className="w-full flex justify-between items-center">
                        <h2 className="text-sm font-semibold text-secondary">
                            {pluralize(message.visualizations.length, 'insight')} analyzed
                        </h2>
                        {message.visualizations.length > 1 && (
                            <LemonButton
                                icon={<IconExpand />}
                                size="xsmall"
                                type="tertiary"
                                onClick={() => openMultiVisualizationModal(insights)}
                                tooltip="View all insights in detail"
                            >
                                Expand
                            </LemonButton>
                        )}
                    </div>
                    <MultiVisualizationMosaic insights={insights} />
                    {message.commentary && <MarkdownMessage content={message.commentary} id="multi-viz-commentary" />}
                </div>
            </div>
        </div>
    )
}
