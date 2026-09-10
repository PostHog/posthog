import './EvaluationsPreview.scss'

import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface PreviewEvaluation {
    id: string
    name: string
    /** Evaluator type, tagged the way the templates gallery tags them. */
    kind: { label: string; tag: LemonTagType }
    passRate: string
    /** Seven days of pass rate, 0-100, oldest first. Drives the bar chart. */
    series: number[]
    verdicts: { pass: boolean; text: string }[]
}

// Example evaluations - hand-authored, not real data. `id` keys the radio that
// drives the `:checked ~` selection styles.
const EVALUATIONS: PreviewEvaluation[] = [
    {
        id: 'accuracy',
        name: 'Answer accuracy',
        kind: { label: 'LLM judge', tag: 'caution' },
        passRate: '94%',
        series: [81, 84, 88, 86, 91, 93, 94],
        verdicts: [
            { pass: true, text: 'Cites the correct refund window' },
            { pass: false, text: 'Invents a plan tier that does not exist' },
            { pass: true, text: 'Matches the export docs step by step' },
        ],
    },
    {
        id: 'links',
        name: 'Links to the docs',
        kind: { label: 'Hog', tag: 'option' },
        passRate: '88%',
        series: [90, 87, 85, 82, 86, 89, 88],
        verdicts: [
            { pass: true, text: 'Reply contains a posthog.com/docs link' },
            { pass: true, text: 'Links the export guide' },
            { pass: false, text: 'No docs link in a how-to answer' },
        ],
    },
    {
        id: 'sentiment',
        name: 'User sentiment',
        kind: { label: 'Sentiment', tag: 'success' },
        passRate: '81%',
        series: [76, 78, 74, 80, 83, 79, 81],
        verdicts: [
            { pass: true, text: 'Positive: "perfect, that fixed it"' },
            { pass: true, text: 'Neutral: "ok, and the annual plan?"' },
            { pass: false, text: 'Negative: "this is the third time I ask"' },
        ],
    },
]

const CHART_WIDTH = 140
const CHART_HEIGHT = 40
const BAR_GAP = 6
const BAR_WIDTH = (CHART_WIDTH - BAR_GAP * 6) / 7
// Pass rates cluster in the 80-100 band, so a chart anchored at 0 reads as flat.
const CHART_FLOOR = 60

/**
 * Example-data preview for the evaluations empty state: the evaluation list wired
 * to a pass-rate card and a verdict feed, so picking an evaluation shows its trend
 * and its latest judgments. Three hidden radios drive `:checked ~` styles - no
 * timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Per-evaluation content is stacked in `__swap` grids and crossfaded, so
 * switching never changes the layout's size.
 */
export function EvaluationsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('EvaluationsPreview', isStatic && 'EvaluationsPreview--static')}>
            {EVALUATIONS.map((evaluation, i) => (
                <input
                    key={evaluation.id}
                    type="radio"
                    name="evaluations-preview-evaluation"
                    id={`evaluations-preview-${evaluation.id}`}
                    defaultChecked={i === 0}
                    className="EvaluationsPreview__radio"
                />
            ))}

            <div className="EvaluationsPreview__list">
                <div className="EvaluationsPreview__head">
                    <span className="EvaluationsPreview__title">Evaluations</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="EvaluationsPreview__rows">
                    {EVALUATIONS.map((evaluation) => (
                        <label
                            key={evaluation.id}
                            htmlFor={`evaluations-preview-${evaluation.id}`}
                            className={`EvaluationsPreview__row EvaluationsPreview__row--${evaluation.id}`}
                        >
                            <span
                                className={`EvaluationsPreview__vradio EvaluationsPreview__vradio--${evaluation.id}`}
                                aria-hidden="true"
                            />
                            <span className="EvaluationsPreview__name">{evaluation.name}</span>
                            <LemonTag size="small" type={evaluation.kind.tag}>
                                {evaluation.kind.label}
                            </LemonTag>
                            <span className="EvaluationsPreview__running">
                                <span className="EvaluationsPreview__running-dot" aria-hidden="true" />
                                Running
                            </span>
                        </label>
                    ))}
                </div>
                <div className="EvaluationsPreview__hint">Select an evaluation to see how it scores.</div>
            </div>

            <div className="EvaluationsPreview__stats">
                <div className="EvaluationsPreview__spark-head">
                    <span className="EvaluationsPreview__spark-title">Pass rate, last 7 days</span>
                </div>
                <div className="EvaluationsPreview__spark-value EvaluationsPreview__swap">
                    {EVALUATIONS.map((evaluation) => (
                        <span key={evaluation.id} className={`EvaluationsPreview__when-${evaluation.id}`}>
                            {evaluation.passRate}
                        </span>
                    ))}
                </div>
                <div className="EvaluationsPreview__swap">
                    {EVALUATIONS.map((evaluation) => (
                        <svg
                            key={evaluation.id}
                            className={`EvaluationsPreview__chart EvaluationsPreview__when-${evaluation.id}`}
                            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            {evaluation.series.map((value, i) => {
                                const height = ((value - CHART_FLOOR) / (100 - CHART_FLOOR)) * CHART_HEIGHT
                                return (
                                    <rect
                                        key={i}
                                        className="EvaluationsPreview__bar"
                                        x={i * (BAR_WIDTH + BAR_GAP)}
                                        y={CHART_HEIGHT - height}
                                        width={BAR_WIDTH}
                                        height={height}
                                        rx={1.5}
                                    />
                                )
                            })}
                        </svg>
                    ))}
                </div>
            </div>

            <div className="EvaluationsPreview__feed">
                {[0, 1, 2].map((rowIndex) => (
                    <div key={rowIndex} className="EvaluationsPreview__swap EvaluationsPreview__verdict-row">
                        {EVALUATIONS.map((evaluation) => {
                            const verdict = evaluation.verdicts[rowIndex]
                            return (
                                <span
                                    key={evaluation.id}
                                    className={`EvaluationsPreview__verdict EvaluationsPreview__when-${evaluation.id}`}
                                >
                                    <span
                                        className={cn(
                                            'EvaluationsPreview__mark',
                                            verdict.pass
                                                ? 'EvaluationsPreview__mark--pass'
                                                : 'EvaluationsPreview__mark--fail'
                                        )}
                                    >
                                        {verdict.pass ? '✓' : '✗'}
                                    </span>
                                    <span className="EvaluationsPreview__verdict-text">{verdict.text}</span>
                                </span>
                            )
                        })}
                    </div>
                ))}
            </div>
        </div>
    )
}
