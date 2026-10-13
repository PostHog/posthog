import './ClustersPreview.scss'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

interface PreviewCluster {
    id: string
    name: string
    share: string
    traces: number
    sample: string
    /** Scatter positions in the 200x110 viewBox. */
    points: [number, number][]
}

// Example clusters - hand-authored, not real data. `id` keys the radio that drives
// the `:checked ~` selection styles and the highlighted dots.
const CLUSTERS: PreviewCluster[] = [
    {
        id: 'billing',
        name: 'Billing questions',
        share: '38%',
        traces: 412,
        sample: '"Why did my invoice go up this month?"',
        points: [
            [38, 34],
            [46, 22],
            [52, 40],
            [30, 48],
            [58, 30],
            [42, 54],
            [64, 46],
            [34, 20],
            [50, 58],
            [26, 34],
        ],
    },
    {
        id: 'bugs',
        name: 'Bug reports',
        share: '27%',
        traces: 291,
        sample: '"The export button does nothing on Safari"',
        points: [
            [132, 28],
            [144, 40],
            [124, 44],
            [150, 24],
            [138, 56],
            [158, 46],
            [128, 18],
            [162, 32],
        ],
    },
    {
        id: 'howto',
        name: 'Feature how-tos',
        share: '21%',
        traces: 227,
        sample: '"How do I share a dashboard with my team?"',
        points: [
            [92, 82],
            [104, 92],
            [84, 94],
            [110, 78],
            [96, 70],
            [118, 90],
            [78, 80],
        ],
    },
]

/**
 * Example-data preview for the clusters empty state: a scatter of traces wired to
 * the cluster list, so picking a cluster lights up its dots and shows what those
 * conversations were about. Three hidden radios drive `:checked ~` styles - no
 * timers or state, per the preview rules in the `building-product-empty-states`
 * skill. In `waiting-for-data` a pinned row reads as listening for the first run.
 */
export function ClustersPreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ClustersPreview', isStatic && 'ClustersPreview--static')}>
            {CLUSTERS.map((cluster, i) => (
                <input
                    key={cluster.id}
                    type="radio"
                    name="clusters-preview-cluster"
                    id={`clusters-preview-${cluster.id}`}
                    defaultChecked={i === 0}
                    className="ClustersPreview__radio"
                />
            ))}

            <div className="ClustersPreview__plot">
                <div className="ClustersPreview__head">
                    <span className="ClustersPreview__title">Traces, last 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <svg className="ClustersPreview__scatter" viewBox="0 0 200 110" aria-hidden="true">
                    {CLUSTERS.map((cluster) => (
                        <g key={cluster.id} className={`ClustersPreview__group ClustersPreview__group--${cluster.id}`}>
                            {cluster.points.map(([x, y], i) => (
                                <circle key={i} className="ClustersPreview__point" cx={x} cy={y} r={3.5} />
                            ))}
                        </g>
                    ))}
                </svg>
            </div>

            <div className="ClustersPreview__list">
                {CLUSTERS.map((cluster) => (
                    <label
                        key={cluster.id}
                        htmlFor={`clusters-preview-${cluster.id}`}
                        className={`ClustersPreview__row ClustersPreview__row--${cluster.id}`}
                    >
                        <span
                            className={`ClustersPreview__swatch ClustersPreview__swatch--${cluster.id}`}
                            aria-hidden="true"
                        />
                        <span className="ClustersPreview__name">{cluster.name}</span>
                        <span className="ClustersPreview__share">{cluster.share}</span>
                    </label>
                ))}
                {mode === 'waiting-for-data' ? (
                    <div className="ClustersPreview__listening">
                        <span className="ClustersPreview__listening-dot" aria-hidden="true" />
                        Listening for the first clustering run
                    </div>
                ) : (
                    <div className="ClustersPreview__hint">Select a cluster to see what it groups.</div>
                )}
            </div>

            <div className="ClustersPreview__detail">
                <div className="ClustersPreview__swap">
                    {CLUSTERS.map((cluster) => (
                        <span key={cluster.id} className={`ClustersPreview__when-${cluster.id}`}>
                            <span className="ClustersPreview__detail-title">{cluster.name}</span>
                            <span className="ClustersPreview__detail-meta">{cluster.traces} traces</span>
                        </span>
                    ))}
                </div>
                <div className="ClustersPreview__swap">
                    {CLUSTERS.map((cluster) => (
                        <span
                            key={cluster.id}
                            className={`ClustersPreview__sample ClustersPreview__when-${cluster.id}`}
                        >
                            {cluster.sample}
                        </span>
                    ))}
                </div>
            </div>
        </div>
    )
}
