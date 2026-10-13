import './SupportPreview.scss'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored falling first-response-time series for the stat card sparkline.
const SPARK_LINE = 'M 0 12 L 10 14 L 20 13 L 30 17 L 40 16 L 50 20.5 L 60 19.5 L 70 24 L 80 25.5 L 90 28 L 100 29.5'
const SPARK_AREA = `${SPARK_LINE} L 100 40 L 0 40 Z`

/**
 * Example-data preview for the Support empty state: the ticket inbox wired to a mini
 * chat widget on a fake site, so sending the customer's typed message makes a new
 * ticket crossfade in at the top of the inbox and ticks the count up. The whole
 * interaction is one hidden checkbox driving `:checked ~` styles - no timers or
 * state, per the preview rules in the `building-product-empty-states` skill. The new
 * row and the count swap in fixed slots, so sending never changes the layout's size.
 * In `waiting-for-data` mode the inbox pins a listening row.
 */
export function SupportPreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('SupportPreview', isStatic && 'SupportPreview--static')}>
            {/* Sent state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="support-preview-send" className="SupportPreview__checkbox" />

            <div className="SupportPreview__inbox">
                <div className="SupportPreview__head">
                    <span className="SupportPreview__title">Inbox</span>
                    <span className="SupportPreview__count SupportPreview__swap">
                        <span className="SupportPreview__when-off">3 tickets</span>
                        <span className="SupportPreview__count--live SupportPreview__when-on">4 tickets</span>
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                {mode === 'waiting-for-data' ? (
                    <div className="SupportPreview__listening">
                        <Spinner className="text-sm" />
                        Listening for your first ticket…
                    </div>
                ) : null}

                <div className="SupportPreview__rows">
                    {/* The row the widget's message becomes. Always occupies its slot
                        (no layout shift); only its opacity follows the checkbox. */}
                    <div className="SupportPreview__row SupportPreview__row--new">
                        <span className="SupportPreview__num">#482</span>
                        <span className="SupportPreview__who">
                            <span className="SupportPreview__person">Mia Chen</span>
                            <span className="SupportPreview__subject">The export button isn't working</span>
                        </span>
                        <span className="SupportPreview__status SupportPreview__status--new">New</span>
                        <span className="SupportPreview__sla">SLA 4h</span>
                    </div>
                    <div className="SupportPreview__row">
                        <span className="SupportPreview__num">
                            #481
                            <span className="SupportPreview__unread" aria-hidden="true" />
                        </span>
                        <span className="SupportPreview__who">
                            <span className="SupportPreview__person">Albert Einstein</span>
                            <span className="SupportPreview__subject">Can't invite teammates</span>
                        </span>
                        <span className="SupportPreview__status SupportPreview__status--open">Open</span>
                        <span className="SupportPreview__sla SupportPreview__sla--due">1h left</span>
                    </div>
                    <div className="SupportPreview__row">
                        <span className="SupportPreview__num">#479</span>
                        <span className="SupportPreview__who">
                            <span className="SupportPreview__person">Nikola Tesla</span>
                            <span className="SupportPreview__subject">Question about billing seats</span>
                        </span>
                        <span className="SupportPreview__status">Pending</span>
                        <span className="SupportPreview__sla">SLA met</span>
                    </div>
                    <div className="SupportPreview__row">
                        <span className="SupportPreview__num">#476</span>
                        <span className="SupportPreview__who">
                            <span className="SupportPreview__person">Niels Bohr</span>
                            <span className="SupportPreview__subject">Feature request: dark mode</span>
                        </span>
                        <span className="SupportPreview__status SupportPreview__status--solved">Solved</span>
                        <span className="SupportPreview__sla">SLA met</span>
                    </div>
                </div>
            </div>

            <div className="SupportPreview__site">
                <div className="SupportPreview__chrome">
                    <span className="SupportPreview__chrome-dot" />
                    <span className="SupportPreview__chrome-dot" />
                    <span className="SupportPreview__chrome-dot" />
                    <span className="SupportPreview__url">yourapp.com</span>
                </div>
                <div className="SupportPreview__widget">
                    <div className="SupportPreview__widget-head">Chat with us</div>
                    <div className="SupportPreview__bubble SupportPreview__bubble--agent">Hi! How can we help?</div>
                    {/* Draft and sent variants stacked in one slot and crossfaded. */}
                    <div className="SupportPreview__swap">
                        <span className="SupportPreview__draft SupportPreview__when-off">
                            The export button isn't working
                            <span className="SupportPreview__typing" aria-hidden="true">
                                <span />
                                <span />
                                <span />
                            </span>
                        </span>
                        <span className="SupportPreview__bubble SupportPreview__bubble--user SupportPreview__when-on">
                            The export button isn't working
                        </span>
                    </div>
                    <div className="SupportPreview__widget-foot">
                        <span className="SupportPreview__sent-note SupportPreview__swap">
                            <span className="SupportPreview__when-off">Also reaches you by email and Slack</span>
                            <span className="SupportPreview__when-on">Delivered · ticket #482 opened</span>
                        </span>
                        <label htmlFor="support-preview-send" className="SupportPreview__send">
                            Send
                        </label>
                    </div>
                </div>
            </div>

            <div className="SupportPreview__spark">
                <div className="SupportPreview__spark-head">
                    <span className="SupportPreview__spark-title">Median first response · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="SupportPreview__spark-value">
                    42m
                    <span className="SupportPreview__spark-delta">▼ 18%</span>
                </div>

                <div className="SupportPreview__spark-chart">
                    <svg
                        className="SupportPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="SupportPreview__spark-area" d={SPARK_AREA} />
                        <path className="SupportPreview__spark-line" d={SPARK_LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="SupportPreview__spark-trace"
                            d={SPARK_LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                </div>
            </div>
        </div>
    )
}
