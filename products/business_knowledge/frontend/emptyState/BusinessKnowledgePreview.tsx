import './BusinessKnowledgePreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface PreviewSource {
    id: string
    name: string
    kind: string
    chunks: number
    question: string
    answer: string
}

// Example sources - hand-authored, not real data. `id` keys the radio that drives
// the `:checked ~` selection styles.
const SOURCES: PreviewSource[] = [
    {
        id: 'pricing',
        name: 'Pricing page',
        kind: 'URL · refreshes daily',
        chunks: 14,
        question: 'Which customers are on a plan with usage limits?',
        answer: 'Your Free plan caps events at 1M a month, so I filtered to organizations on that plan. 212 match.',
    },
    {
        id: 'refunds',
        name: 'Refund policy',
        kind: 'Text · manual',
        chunks: 6,
        question: 'Draft a reply to a refund request from last week',
        answer: 'Your policy allows a prorated refund within 14 days of cancelling, so this one qualifies. Here is a draft.',
    },
    {
        id: 'brand',
        name: 'Brand guidelines',
        kind: 'PDF · manual',
        chunks: 9,
        question: 'Write the survey intro for the new onboarding flow',
        answer: 'Kept it in sentence case and dropped the exclamation marks, per your voice guide. Two options below.',
    },
]

/**
 * Example-data preview for the business knowledge empty state: the source list
 * wired to a mini PostHog AI thread, so picking a source shows an answer that
 * cites it. Three hidden radios drive `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill. Per-source
 * messages are stacked in `__swap` grids and crossfaded, so switching never
 * changes the layout's size.
 */
export function BusinessKnowledgePreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('BusinessKnowledgePreview', isStatic && 'BusinessKnowledgePreview--static')}>
            {SOURCES.map((source, i) => (
                <input
                    key={source.id}
                    type="radio"
                    name="business-knowledge-preview-source"
                    id={`business-knowledge-preview-${source.id}`}
                    defaultChecked={i === 0}
                    className="BusinessKnowledgePreview__radio"
                />
            ))}

            <div className="BusinessKnowledgePreview__list">
                <div className="BusinessKnowledgePreview__head">
                    <span className="BusinessKnowledgePreview__title">Sources</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="BusinessKnowledgePreview__rows">
                    {SOURCES.map((source) => (
                        <label
                            key={source.id}
                            htmlFor={`business-knowledge-preview-${source.id}`}
                            className={`BusinessKnowledgePreview__row BusinessKnowledgePreview__row--${source.id}`}
                        >
                            <span
                                className={`BusinessKnowledgePreview__vradio BusinessKnowledgePreview__vradio--${source.id}`}
                                aria-hidden="true"
                            />
                            <span className="BusinessKnowledgePreview__copy">
                                <span className="BusinessKnowledgePreview__name">{source.name}</span>
                                <span className="BusinessKnowledgePreview__meta">{source.kind}</span>
                            </span>
                            <span className="BusinessKnowledgePreview__status">
                                <span className="BusinessKnowledgePreview__status-dot" aria-hidden="true" />
                                {source.chunks} chunks
                            </span>
                        </label>
                    ))}
                </div>
                <div className="BusinessKnowledgePreview__hint">Select a source to see PostHog AI use it.</div>
            </div>

            <div className="BusinessKnowledgePreview__thread">
                <div className="BusinessKnowledgePreview__bubble BusinessKnowledgePreview__bubble--user">
                    <span className="BusinessKnowledgePreview__swap">
                        {SOURCES.map((source) => (
                            <span key={source.id} className={`BusinessKnowledgePreview__when-${source.id}`}>
                                {source.question}
                            </span>
                        ))}
                    </span>
                </div>
                <div className="BusinessKnowledgePreview__bubble BusinessKnowledgePreview__bubble--ai">
                    <span className="BusinessKnowledgePreview__swap">
                        {SOURCES.map((source) => (
                            <span key={source.id} className={`BusinessKnowledgePreview__when-${source.id}`}>
                                {source.answer}
                                <span className="BusinessKnowledgePreview__cursor" aria-hidden="true" />
                            </span>
                        ))}
                    </span>
                    <span className="BusinessKnowledgePreview__swap">
                        {SOURCES.map((source) => (
                            <span
                                key={source.id}
                                className={`BusinessKnowledgePreview__cite BusinessKnowledgePreview__when-${source.id}`}
                            >
                                From {source.name}
                            </span>
                        ))}
                    </span>
                </div>
            </div>
        </div>
    )
}
