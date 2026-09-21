import './WebScriptPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored 7-day invocation sparklines for the script rows. The hero's series
// only shows once its script is enabled.
const SPARK_CONSENT = 'M 0 13 L 16 11 L 32 12.5 L 48 9.5 L 64 10.5 L 80 8 L 100 7'
const SPARK_BANNER = 'M 0 15.5 L 16 15.5 L 32 15.2 L 48 10 L 64 7.5 L 80 5.5 L 100 4'

/**
 * Example-data preview for the web scripts empty state: the scripts list wired to a
 * mini website, so enabling the announcement banner script makes the banner appear
 * on the site and lights up the script's invocation sparkline. The whole interaction
 * is one hidden checkbox driving `:checked ~` styles - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill. On/off pairs are
 * stacked in `__swap` grids and crossfaded, so enabling never changes the layout's size.
 */
export function WebScriptPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('WebScriptPreview', isStatic && 'WebScriptPreview--static')}>
            {/* Enabled state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="web-script-preview-toggle" className="WebScriptPreview__checkbox" />

            <div className="WebScriptPreview__panel">
                <div className="WebScriptPreview__head">
                    <span className="WebScriptPreview__title">Web scripts</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="WebScriptPreview__rows">
                    <div className="WebScriptPreview__row">
                        <span className="WebScriptPreview__name">Cookie consent</span>
                        <svg
                            className="WebScriptPreview__row-spark"
                            viewBox="0 0 100 20"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            <path
                                className="WebScriptPreview__row-line"
                                d={SPARK_CONSENT}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="WebScriptPreview__row-trace"
                                d={SPARK_CONSENT}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </svg>
                        <span className="WebScriptPreview__invocations">8.2k</span>
                        <span className="WebScriptPreview__switch WebScriptPreview__switch--on" aria-hidden="true" />
                    </div>
                    <label
                        htmlFor="web-script-preview-toggle"
                        className="WebScriptPreview__row WebScriptPreview__row--hero"
                    >
                        <span className="WebScriptPreview__name">Announcement banner</span>
                        <svg
                            className="WebScriptPreview__row-spark"
                            viewBox="0 0 100 20"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            <path
                                className="WebScriptPreview__row-line WebScriptPreview__row-line--hero"
                                d={SPARK_BANNER}
                                vectorEffect="non-scaling-stroke"
                            />
                        </svg>
                        <span className="WebScriptPreview__swap">
                            <span className="WebScriptPreview__invocations WebScriptPreview__when-off">–</span>
                            <span className="WebScriptPreview__invocations WebScriptPreview__invocations--live WebScriptPreview__when-on">
                                1.4k
                            </span>
                        </span>
                        <span className="WebScriptPreview__switch" aria-hidden="true" />
                    </label>
                    <div className="WebScriptPreview__row">
                        <span className="WebScriptPreview__name">Feedback widget</span>
                        <svg
                            className="WebScriptPreview__row-spark"
                            viewBox="0 0 100 20"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            <path
                                className="WebScriptPreview__row-line WebScriptPreview__row-line--flat"
                                d="M 0 16 L 100 16"
                                vectorEffect="non-scaling-stroke"
                            />
                        </svg>
                        <span className="WebScriptPreview__invocations">–</span>
                        <span className="WebScriptPreview__switch" aria-hidden="true" />
                    </div>
                </div>

                <div className="WebScriptPreview__hint WebScriptPreview__swap">
                    <span className="WebScriptPreview__when-off">
                        Enable the banner script to run it on the site below.
                    </span>
                    <span className="WebScriptPreview__when-on">Live on every page. Flip it off to remove it.</span>
                </div>
            </div>

            <div className="WebScriptPreview__site">
                <div className="WebScriptPreview__chrome">
                    <span className="WebScriptPreview__chrome-dot" />
                    <span className="WebScriptPreview__chrome-dot" />
                    <span className="WebScriptPreview__chrome-dot" />
                    <span className="WebScriptPreview__url">yourapp.com</span>
                </div>
                <div className="WebScriptPreview__screen">
                    {/* The banner the script injects. Always occupies its slot (no layout
                        shift); only its opacity follows the switch. */}
                    <div className="WebScriptPreview__banner WebScriptPreview__when-on">
                        Spring sale: 20% off annual plans this week
                    </div>
                    <span className="WebScriptPreview__skel" style={{ '--w': '70%' } as React.CSSProperties} />
                    <span className="WebScriptPreview__skel" style={{ '--w': '90%' } as React.CSSProperties} />
                    <span className="WebScriptPreview__skel" style={{ '--w': '45%' } as React.CSSProperties} />
                    <div className="WebScriptPreview__console">
                        <span className="WebScriptPreview__console-key">site_app:announcement-banner</span>
                        <span className="WebScriptPreview__swap">
                            <span className="WebScriptPreview__console-val WebScriptPreview__when-off">disabled</span>
                            <span className="WebScriptPreview__console-val WebScriptPreview__console-val--on WebScriptPreview__when-on">
                                loaded
                            </span>
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}
