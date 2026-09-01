import './ActionsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored sign-up series for the stat card. The "after" series adds the click
// the user just made at the far right.
const LINE_BEFORE = 'M 0 30 L 14 27 L 28 29 L 42 24 L 56 26 L 70 21 L 84 22 L 100 18'
const LINE_AFTER = 'M 0 30 L 14 27 L 28 29 L 42 24 L 56 26 L 70 21 L 84 22 L 92 18 L 100 8'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the actions empty state: a mini pricing page, the action
 * that watches it, and the sign-up count it feeds. Clicking "Start free trial" in the
 * app fires an autocapture event - the action matches it, its row lights up, and the
 * count steps up. One hidden checkbox drives it all via `:checked ~` styles - no timers
 * or state, per the preview rules in the `building-product-empty-states` skill.
 * Before/after pairs are stacked in `__swap` grids and crossfaded, so nothing shifts.
 */
export function ActionsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ActionPreview', isStatic && 'ActionPreview--static')}>
            {/* Click state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="action-preview-click" className="ActionPreview__checkbox" />

            <div className="ActionPreview__app">
                <div className="ActionPreview__chrome">
                    <span className="ActionPreview__chrome-dot" />
                    <span className="ActionPreview__chrome-dot" />
                    <span className="ActionPreview__chrome-dot" />
                    <span className="ActionPreview__url">yourapp.com/pricing</span>
                </div>
                <div className="ActionPreview__screen">
                    <div className="ActionPreview__plan">
                        <span className="ActionPreview__plan-name">Pro</span>
                        <span className="ActionPreview__plan-price">$29/mo</span>
                    </div>
                    <label htmlFor="action-preview-click" className="ActionPreview__cta">
                        Start free trial
                    </label>
                    <div className="ActionPreview__toast-slot ActionPreview__swap" aria-hidden="true">
                        <span className="ActionPreview__toast-spacer ActionPreview__when-before" />
                        <span className="ActionPreview__toast ActionPreview__when-after">
                            $autocapture · button.cta-primary
                        </span>
                    </div>
                    <div className="ActionPreview__hint ActionPreview__swap">
                        <span className="ActionPreview__when-before">Click the button to send an event.</span>
                        <span className="ActionPreview__when-after">
                            Matched by "Signed up" and counted below. Click again to undo.
                        </span>
                    </div>
                </div>
            </div>

            <div className="ActionPreview__panel">
                <div className="ActionPreview__head">
                    <span className="ActionPreview__title">Actions</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="ActionPreview__rows">
                    <div className="ActionPreview__row ActionPreview__row--hero">
                        <span className="ActionPreview__dot" aria-hidden="true" />
                        <span className="ActionPreview__action">
                            <span className="ActionPreview__name">Signed up</span>
                            <span className="ActionPreview__match">button.cta-primary on /pricing</span>
                        </span>
                        <span className="ActionPreview__badge ActionPreview__when-after">matched</span>
                        <span className="ActionPreview__count ActionPreview__swap">
                            <span className="ActionPreview__when-before">1,284</span>
                            <span className="ActionPreview__count--bumped ActionPreview__when-after">1,285</span>
                        </span>
                    </div>
                    <div className="ActionPreview__row">
                        <span className="ActionPreview__dot" aria-hidden="true" />
                        <span className="ActionPreview__action">
                            <span className="ActionPreview__name">Started checkout</span>
                            <span className="ActionPreview__match">3 events</span>
                        </span>
                        <span className="ActionPreview__count">642</span>
                    </div>
                    <div className="ActionPreview__row">
                        <span className="ActionPreview__dot" aria-hidden="true" />
                        <span className="ActionPreview__action">
                            <span className="ActionPreview__name">Invited a teammate</span>
                            <span className="ActionPreview__match">2 events</span>
                        </span>
                        <span className="ActionPreview__count">318</span>
                    </div>
                </div>

                <div className="ActionPreview__spark">
                    <div className="ActionPreview__spark-head">
                        <span className="ActionPreview__spark-title">Signed up · 7 days</span>
                    </div>
                    <div className="ActionPreview__spark-value">
                        <span className="ActionPreview__swap">
                            <span className="ActionPreview__when-before">1,284</span>
                            <span className="ActionPreview__when-after">1,285</span>
                        </span>
                    </div>
                    <svg
                        className="ActionPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="ActionPreview__spark-g ActionPreview__when-before">
                            <path className="ActionPreview__spark-area" d={areaPath(LINE_BEFORE)} />
                            <path
                                className="ActionPreview__spark-line"
                                d={LINE_BEFORE}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="ActionPreview__spark-trace"
                                d={LINE_BEFORE}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="ActionPreview__spark-g ActionPreview__when-after">
                            <path className="ActionPreview__spark-area" d={areaPath(LINE_AFTER)} />
                            <path
                                className="ActionPreview__spark-line"
                                d={LINE_AFTER}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="ActionPreview__spark-trace"
                                d={LINE_AFTER}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    </svg>
                </div>
            </div>
        </div>
    )
}
