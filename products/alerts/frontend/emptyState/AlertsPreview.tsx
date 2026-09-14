import './AlertsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored weekly series climbing toward the threshold, so lowering the
// threshold puts the last two weeks above it.
const LINE = 'M 0 32 L 14 31 L 28 28 L 42 26 L 56 22 L 70 17 L 84 12 L 100 8'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the alerts empty state: an insight being watched, and the
 * threshold that decides when it fires. Lowering the threshold puts the series above
 * it, so the alert fires and the notification it sent shows up in the list. One hidden
 * checkbox drives it via `:checked ~` styles - no timers or state, per the preview
 * rules in the `building-product-empty-states` skill. Before/after pairs share a
 * `__swap` grid cell and crossfade, so no row moves.
 */
export function AlertsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('AlertPreview', isStatic && 'AlertPreview--static')}>
            {/* Firing state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="alert-preview-lower" className="AlertPreview__checkbox" />

            <div className="AlertPreview__chart">
                <div className="AlertPreview__head">
                    <span className="AlertPreview__title">Weekly active users</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="AlertPreview__plot">
                    <svg
                        className="AlertPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="AlertPreview__spark-area" d={areaPath(LINE)} />
                        <path className="AlertPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="AlertPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                        <line
                            className="AlertPreview__threshold-line"
                            x1="0"
                            x2="100"
                            y1="6"
                            y2="6"
                            vectorEffect="non-scaling-stroke"
                        />
                        {/* Where the series passes the lowered threshold. The plot is scaled
                            unevenly, so the marker is an ellipse that renders round. */}
                        <ellipse className="AlertPreview__cross" cx="68" cy="18" rx="1.1" ry="2.5" />
                    </svg>
                </div>

                <label htmlFor="alert-preview-lower" className="AlertPreview__threshold">
                    <span className="AlertPreview__threshold-label">Notify me above</span>
                    <span className="AlertPreview__threshold-value AlertPreview__swap">
                        <span className="AlertPreview__when-before">12,000</span>
                        <span className="AlertPreview__when-after">9,000</span>
                    </span>
                    <span className="AlertPreview__threshold-hint AlertPreview__swap">
                        <span className="AlertPreview__when-before">Click to lower it</span>
                        <span className="AlertPreview__when-after">Click to raise it back</span>
                    </span>
                </label>
            </div>

            <div className="AlertPreview__panel">
                <div className="AlertPreview__head">
                    <span className="AlertPreview__title">Alerts</span>
                </div>

                <div className="AlertPreview__rows">
                    <div className="AlertPreview__row">
                        <span className="AlertPreview__row-main">
                            <span className="AlertPreview__row-title AlertPreview__swap">
                                <span className="AlertPreview__when-before">Weekly active users above 12,000</span>
                                <span className="AlertPreview__when-after">Weekly active users above 9,000</span>
                            </span>
                            <span className="AlertPreview__row-meta AlertPreview__swap">
                                <span className="AlertPreview__when-before">Checked hourly</span>
                                <span className="AlertPreview__when-after">Sent to #product-alerts, 2 minutes ago</span>
                            </span>
                        </span>
                        <span className="AlertPreview__state AlertPreview__swap">
                            <span className="AlertPreview__pill AlertPreview__when-before">Not firing</span>
                            <span className="AlertPreview__pill AlertPreview__pill--firing AlertPreview__when-after">
                                Firing
                            </span>
                        </span>
                    </div>

                    <div className="AlertPreview__row">
                        <span className="AlertPreview__row-main">
                            <span className="AlertPreview__row-title">Checkout errors above 20</span>
                            <span className="AlertPreview__row-meta">Checked daily</span>
                        </span>
                        <span className="AlertPreview__state">
                            <span className="AlertPreview__pill">Not firing</span>
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}
