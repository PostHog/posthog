import './DashboardsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored active-user series, one per date range. The 30-day line carries more
// shape, so switching ranges visibly redraws the tile.
const LINE_7D = 'M 0 26 L 16 24 L 33 25 L 50 20 L 66 21 L 83 16 L 100 14'
const LINE_30D = 'M 0 34 L 14 30 L 28 32 L 42 25 L 56 27 L 70 18 L 84 20 L 100 10'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the dashboards empty state: a four-tile dashboard whose
 * every tile answers to one date range. Switching between 7 and 30 days redraws the
 * chart, the funnel, and both numbers at once, which is the thing a dashboard does
 * that a single insight cannot. Two hidden radios drive it via `:checked ~` styles -
 * no timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Range variants are stacked in `__swap` grids and crossfaded, so nothing shifts.
 */
export function DashboardsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('DashboardPreview', isStatic && 'DashboardPreview--static')}>
            {/* Range selection, before the board so `:checked ~` can style every tile. */}
            <input
                type="radio"
                name="dashboard-preview-range"
                id="dashboard-preview-7d"
                defaultChecked
                className="DashboardPreview__radio"
            />
            <input
                type="radio"
                name="dashboard-preview-range"
                id="dashboard-preview-30d"
                className="DashboardPreview__radio"
            />

            <div className="DashboardPreview__board">
                <div className="DashboardPreview__head">
                    <span className="DashboardPreview__title">Product health</span>
                    <div className="DashboardPreview__ranges">
                        <label
                            htmlFor="dashboard-preview-7d"
                            className="DashboardPreview__range DashboardPreview__range--7d"
                        >
                            7 days
                        </label>
                        <label
                            htmlFor="dashboard-preview-30d"
                            className="DashboardPreview__range DashboardPreview__range--30d"
                        >
                            30 days
                        </label>
                    </div>
                </div>

                <div className="DashboardPreview__grid">
                    <div className="DashboardPreview__tile">
                        <span className="DashboardPreview__tile-title">Active users</span>
                        <span className="DashboardPreview__tile-value DashboardPreview__swap">
                            <span className="DashboardPreview__on-7d">4,182</span>
                            <span className="DashboardPreview__on-30d">12,940</span>
                        </span>
                        <span className="DashboardPreview__tile-delta DashboardPreview__swap">
                            <span className="DashboardPreview__on-7d">+8.2% vs previous</span>
                            <span className="DashboardPreview__on-30d">+14.6% vs previous</span>
                        </span>
                    </div>

                    <div className="DashboardPreview__tile">
                        <span className="DashboardPreview__tile-title">Weekly actives</span>
                        <svg
                            className="DashboardPreview__spark-svg"
                            viewBox="0 0 100 40"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            <g className="DashboardPreview__spark-g DashboardPreview__on-7d">
                                <path className="DashboardPreview__spark-area" d={areaPath(LINE_7D)} />
                                <path
                                    className="DashboardPreview__spark-line"
                                    d={LINE_7D}
                                    vectorEffect="non-scaling-stroke"
                                />
                                <path
                                    className="DashboardPreview__spark-trace"
                                    d={LINE_7D}
                                    pathLength={100}
                                    vectorEffect="non-scaling-stroke"
                                />
                            </g>
                            <g className="DashboardPreview__spark-g DashboardPreview__on-30d">
                                <path className="DashboardPreview__spark-area" d={areaPath(LINE_30D)} />
                                <path
                                    className="DashboardPreview__spark-line"
                                    d={LINE_30D}
                                    vectorEffect="non-scaling-stroke"
                                />
                                <path
                                    className="DashboardPreview__spark-trace"
                                    d={LINE_30D}
                                    pathLength={100}
                                    vectorEffect="non-scaling-stroke"
                                />
                            </g>
                        </svg>
                    </div>

                    <div className="DashboardPreview__tile">
                        <span className="DashboardPreview__tile-title">Sign-up funnel</span>
                        <div className="DashboardPreview__funnel">
                            <span className="DashboardPreview__bar DashboardPreview__bar--1" />
                            <span className="DashboardPreview__bar DashboardPreview__bar--2" />
                            <span className="DashboardPreview__bar DashboardPreview__bar--3" />
                        </div>
                        <span className="DashboardPreview__tile-delta DashboardPreview__swap">
                            <span className="DashboardPreview__on-7d">31% complete</span>
                            <span className="DashboardPreview__on-30d">27% complete</span>
                        </span>
                    </div>

                    <div className="DashboardPreview__tile">
                        <span className="DashboardPreview__tile-title">Top pages</span>
                        <div className="DashboardPreview__list">
                            <span className="DashboardPreview__list-row">
                                <span className="DashboardPreview__list-key">/pricing</span>
                                <span className="DashboardPreview__swap DashboardPreview__list-value">
                                    <span className="DashboardPreview__on-7d">1,204</span>
                                    <span className="DashboardPreview__on-30d">4,860</span>
                                </span>
                            </span>
                            <span className="DashboardPreview__list-row">
                                <span className="DashboardPreview__list-key">/docs</span>
                                <span className="DashboardPreview__swap DashboardPreview__list-value">
                                    <span className="DashboardPreview__on-7d">932</span>
                                    <span className="DashboardPreview__on-30d">3,417</span>
                                </span>
                            </span>
                            <span className="DashboardPreview__list-row">
                                <span className="DashboardPreview__list-key">/blog</span>
                                <span className="DashboardPreview__swap DashboardPreview__list-value">
                                    <span className="DashboardPreview__on-7d">618</span>
                                    <span className="DashboardPreview__on-30d">2,205</span>
                                </span>
                            </span>
                        </div>
                    </div>
                </div>

                <div className="DashboardPreview__foot">
                    <LemonTag size="small">example data</LemonTag>
                    <span className="DashboardPreview__hint">Switch the range to move every tile at once.</span>
                </div>
            </div>
        </div>
    )
}
