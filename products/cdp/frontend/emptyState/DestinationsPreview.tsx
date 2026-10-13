import './DestinationsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored 24-hour delivery series for the stat card.
const LINE = 'M 0 28 L 14 24 L 28 26 L 42 18 L 56 20 L 70 12 L 84 10 L 100 6'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the destinations empty state: the destinations list wired to a
 * mini chat window, so enabling the Slack destination makes the alert message appear in
 * the channel and starts counting deliveries. One hidden checkbox drives it via `:checked ~`
 * styles - no timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Off/on pairs share a `__swap` grid cell and crossfade, so nothing moves.
 */
export function DestinationsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('DestinationsPreview', isStatic && 'DestinationsPreview--static')}>
            {/* Enabled state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="destinations-preview-toggle" className="DestinationsPreview__checkbox" />

            <div className="DestinationsPreview__panel">
                <div className="DestinationsPreview__head">
                    <span className="DestinationsPreview__title">Destinations</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="DestinationsPreview__rows">
                    <div className="DestinationsPreview__row">
                        <span className="DestinationsPreview__icon DestinationsPreview__icon--warehouse" />
                        <span className="DestinationsPreview__name">
                            Nightly export to BigQuery
                            <span className="DestinationsPreview__meta">Batch, every day at 02:00</span>
                        </span>
                        <span
                            className="DestinationsPreview__switch DestinationsPreview__switch--on"
                            aria-hidden="true"
                        />
                    </div>

                    <label
                        htmlFor="destinations-preview-toggle"
                        className="DestinationsPreview__row DestinationsPreview__row--hero"
                    >
                        <span className="DestinationsPreview__icon DestinationsPreview__icon--chat" />
                        <span className="DestinationsPreview__name">
                            Payment failed alerts to Slack
                            <span className="DestinationsPreview__meta DestinationsPreview__swap">
                                <span className="DestinationsPreview__when-off">Real time, paused</span>
                                <span className="DestinationsPreview__when-on">Real time, on payment_failed</span>
                            </span>
                        </span>
                        <span
                            className="DestinationsPreview__switch DestinationsPreview__switch--hero"
                            aria-hidden="true"
                        />
                    </label>

                    <div className="DestinationsPreview__row">
                        <span className="DestinationsPreview__icon DestinationsPreview__icon--webhook" />
                        <span className="DestinationsPreview__name">
                            Signups to the CRM
                            <span className="DestinationsPreview__meta">Webhook, on user_signed_up</span>
                        </span>
                        <span
                            className="DestinationsPreview__switch DestinationsPreview__switch--on"
                            aria-hidden="true"
                        />
                    </div>
                </div>
            </div>

            <div className="DestinationsPreview__bottom">
                <div className="DestinationsPreview__chat" aria-hidden="true">
                    <div className="DestinationsPreview__chat-head">
                        <span className="DestinationsPreview__chat-dot" />
                        <span className="DestinationsPreview__chat-channel"># payments</span>
                    </div>
                    <div className="DestinationsPreview__chat-body DestinationsPreview__swap">
                        <div className="DestinationsPreview__when-off DestinationsPreview__chat-empty">
                            <span className="DestinationsPreview__ghost" />
                            <span className="DestinationsPreview__ghost DestinationsPreview__ghost--short" />
                            <span className="DestinationsPreview__chat-hint">Enable the destination above</span>
                        </div>
                        <div className="DestinationsPreview__when-on DestinationsPreview__message">
                            <span className="DestinationsPreview__avatar" />
                            <span className="DestinationsPreview__message-body">
                                <span className="DestinationsPreview__message-author">PostHog</span>
                                <span className="DestinationsPreview__message-text">
                                    Payment failed for <b>acme.example.com</b>. Card declined, 3rd attempt.
                                </span>
                            </span>
                        </div>
                    </div>
                </div>

                <div className="DestinationsPreview__stat">
                    <div className="DestinationsPreview__spark-head">
                        <span className="DestinationsPreview__spark-title">Deliveries</span>
                        <span className="DestinationsPreview__spark-caption">Last 24 hours</span>
                    </div>
                    <div className="DestinationsPreview__spark-value DestinationsPreview__swap">
                        <span className="DestinationsPreview__when-off">3,412</span>
                        <span className="DestinationsPreview__when-on">3,458</span>
                    </div>
                    <svg
                        className="DestinationsPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="DestinationsPreview__spark-area" d={areaPath(LINE)} />
                        <path className="DestinationsPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="DestinationsPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                    <span className="DestinationsPreview__footer DestinationsPreview__swap">
                        <span className="DestinationsPreview__when-off">2 destinations on. 9 retries, 0 failed.</span>
                        <span className="DestinationsPreview__when-on">3 destinations on. 9 retries, 0 failed.</span>
                    </span>
                </div>
            </div>
        </div>
    )
}
