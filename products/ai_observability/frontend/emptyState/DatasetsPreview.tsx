import './DatasetsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface PreviewDataset {
    id: string
    name: string
    items: number
    updated: string
    rows: { input: string; expected: string }[]
}

// Example datasets - hand-authored, not real data. `id` keys the radio that drives
// the `:checked ~` selection styles.
const DATASETS: PreviewDataset[] = [
    {
        id: 'support',
        name: 'Support replies',
        items: 48,
        updated: 'updated 2h ago',
        rows: [
            { input: 'How do I export my data?', expected: 'Links to the export docs, mentions CSV and API' },
            { input: 'Can I pause my subscription?', expected: 'Yes, from billing settings, keeps data for 90 days' },
            { input: 'Is there a free tier?', expected: 'Yes, with monthly usage limits per product' },
        ],
    },
    {
        id: 'refunds',
        name: 'Refund policy Q&A',
        items: 21,
        updated: 'updated yesterday',
        rows: [
            { input: 'I was charged twice this month', expected: 'Apologize, confirm the duplicate, offer a refund' },
            { input: 'Refund a plan I cancelled last week?', expected: 'Prorated refund within 14 days of cancelling' },
            { input: 'Do you refund annual plans?', expected: 'Within 30 days of purchase, in full' },
        ],
    },
    {
        id: 'onboarding',
        name: 'Onboarding prompts',
        items: 33,
        updated: 'updated 3d ago',
        rows: [
            { input: 'Set up tracking on a Next.js app', expected: 'Install steps, provider wrapper, env var' },
            { input: "My events aren't showing up", expected: 'Check the API key, host, and ad blockers' },
            { input: 'Invite my team', expected: 'Settings > Members, roles explained' },
        ],
    },
]

/**
 * Example-data preview for the datasets empty state: the dataset list wired to
 * the items table it opens, so picking a dataset shows its inputs and expected
 * outputs. Three hidden radios drive `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill. Per-dataset
 * items are stacked in `__swap` grids and crossfaded, so switching never changes
 * the layout's size.
 */
export function DatasetsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('DatasetsPreview', isStatic && 'DatasetsPreview--static')}>
            {DATASETS.map((dataset, i) => (
                <input
                    key={dataset.id}
                    type="radio"
                    name="datasets-preview-dataset"
                    id={`datasets-preview-${dataset.id}`}
                    defaultChecked={i === 0}
                    className="DatasetsPreview__radio"
                />
            ))}

            <div className="DatasetsPreview__list">
                <div className="DatasetsPreview__head">
                    <span className="DatasetsPreview__title">Datasets</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="DatasetsPreview__rows">
                    {DATASETS.map((dataset) => (
                        <label
                            key={dataset.id}
                            htmlFor={`datasets-preview-${dataset.id}`}
                            className={`DatasetsPreview__row DatasetsPreview__row--${dataset.id}`}
                        >
                            <span
                                className={`DatasetsPreview__vradio DatasetsPreview__vradio--${dataset.id}`}
                                aria-hidden="true"
                            />
                            <span className="DatasetsPreview__copy">
                                <span className="DatasetsPreview__name">{dataset.name}</span>
                                <span className="DatasetsPreview__meta">
                                    {dataset.items} items · {dataset.updated}
                                </span>
                            </span>
                        </label>
                    ))}
                </div>
                <div className="DatasetsPreview__hint">Select a dataset to open its items.</div>
            </div>

            <div className="DatasetsPreview__items">
                <div className="DatasetsPreview__head">
                    <span className="DatasetsPreview__swap">
                        {DATASETS.map((dataset) => (
                            <span
                                key={dataset.id}
                                className={`DatasetsPreview__title DatasetsPreview__when-${dataset.id}`}
                            >
                                {dataset.name}
                            </span>
                        ))}
                    </span>
                    <span className="DatasetsPreview__swap">
                        {DATASETS.map((dataset) => (
                            <span
                                key={dataset.id}
                                className={`DatasetsPreview__count DatasetsPreview__when-${dataset.id}`}
                            >
                                {dataset.items} items
                            </span>
                        ))}
                    </span>
                </div>
                <div className="DatasetsPreview__cols">
                    <span>Input</span>
                    <span>Expected output</span>
                </div>
                {[0, 1, 2].map((rowIndex) => (
                    <div key={rowIndex} className="DatasetsPreview__swap DatasetsPreview__item">
                        {DATASETS.map((dataset) => (
                            <span
                                key={dataset.id}
                                className={`DatasetsPreview__cells DatasetsPreview__when-${dataset.id}`}
                            >
                                <span className="DatasetsPreview__input">{dataset.rows[rowIndex].input}</span>
                                <span className="DatasetsPreview__expected">{dataset.rows[rowIndex].expected}</span>
                            </span>
                        ))}
                    </div>
                ))}
                <div className="DatasetsPreview__incoming">
                    <span className="DatasetsPreview__dot" aria-hidden="true" />
                    New item saved from a trace
                </div>
            </div>
        </div>
    )
}
