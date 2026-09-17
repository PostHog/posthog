import './TransformationsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored 24-hour series of events that passed through the pipeline.
const LINE = 'M 0 24 L 14 22 L 28 25 L 42 17 L 56 19 L 70 13 L 84 11 L 100 7'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the transformations empty state: the ordered transformation list
 * next to one event as it comes out of the pipeline, so enabling GeoIP adds location
 * properties to the event. One hidden checkbox drives it via `:checked ~` styles - no timers
 * or state, per the preview rules in the `building-product-empty-states` skill. The added
 * property lines occupy their rows in both states and only fade in, so nothing moves.
 */
export function TransformationsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('TransformationsPreview', isStatic && 'TransformationsPreview--static')}>
            {/* Enabled state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="transformations-preview-toggle" className="TransformationsPreview__checkbox" />

            <div className="TransformationsPreview__panel">
                <div className="TransformationsPreview__head">
                    <span className="TransformationsPreview__title">Transformations</span>
                    <span className="TransformationsPreview__order">Run in order</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="TransformationsPreview__rows">
                    <div className="TransformationsPreview__row">
                        <span className="TransformationsPreview__step">1</span>
                        <span className="TransformationsPreview__name">
                            Filter out bots
                            <span className="TransformationsPreview__meta">Drops 3.1% of events</span>
                        </span>
                        <span
                            className="TransformationsPreview__switch TransformationsPreview__switch--on"
                            aria-hidden="true"
                        />
                    </div>

                    <label
                        htmlFor="transformations-preview-toggle"
                        className="TransformationsPreview__row TransformationsPreview__row--hero"
                    >
                        <span className="TransformationsPreview__step">2</span>
                        <span className="TransformationsPreview__name">
                            Add GeoIP location
                            <span className="TransformationsPreview__meta TransformationsPreview__swap">
                                <span className="TransformationsPreview__when-off">Paused</span>
                                <span className="TransformationsPreview__when-on">Adds 6 properties</span>
                            </span>
                        </span>
                        <span
                            className="TransformationsPreview__switch TransformationsPreview__switch--hero"
                            aria-hidden="true"
                        />
                    </label>

                    <div className="TransformationsPreview__row">
                        <span className="TransformationsPreview__step">3</span>
                        <span className="TransformationsPreview__name">
                            Drop internal emails
                            <span className="TransformationsPreview__meta">
                                Removes email when it matches your domain
                            </span>
                        </span>
                        <span
                            className="TransformationsPreview__switch TransformationsPreview__switch--on"
                            aria-hidden="true"
                        />
                    </div>
                </div>
            </div>

            <div className="TransformationsPreview__bottom">
                <div className="TransformationsPreview__event" aria-hidden="true">
                    <div className="TransformationsPreview__event-head">
                        <span className="TransformationsPreview__event-name">$pageview</span>
                        <span className="TransformationsPreview__event-when">just now</span>
                    </div>
                    <div className="TransformationsPreview__props">
                        <span className="TransformationsPreview__prop">
                            <span className="TransformationsPreview__key">$current_url</span>
                            <span className="TransformationsPreview__val">/pricing</span>
                        </span>
                        <span className="TransformationsPreview__prop">
                            <span className="TransformationsPreview__key">$browser</span>
                            <span className="TransformationsPreview__val">Firefox</span>
                        </span>
                        <span className="TransformationsPreview__prop TransformationsPreview__prop--added">
                            <span className="TransformationsPreview__key">$geoip_city_name</span>
                            <span className="TransformationsPreview__val">Lisbon</span>
                        </span>
                        <span className="TransformationsPreview__prop TransformationsPreview__prop--added">
                            <span className="TransformationsPreview__key">$geoip_country_code</span>
                            <span className="TransformationsPreview__val">PT</span>
                        </span>
                        <span className="TransformationsPreview__prop TransformationsPreview__prop--added">
                            <span className="TransformationsPreview__key">$geoip_time_zone</span>
                            <span className="TransformationsPreview__val">Europe/Lisbon</span>
                        </span>
                    </div>
                </div>

                <div className="TransformationsPreview__stat">
                    <div className="TransformationsPreview__spark-head">
                        <span className="TransformationsPreview__spark-title">Events transformed</span>
                        <span className="TransformationsPreview__spark-caption">Last 24 hours</span>
                    </div>
                    <div className="TransformationsPreview__spark-value">128k</div>
                    <svg
                        className="TransformationsPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="TransformationsPreview__spark-area" d={areaPath(LINE)} />
                        <path
                            className="TransformationsPreview__spark-line"
                            d={LINE}
                            vectorEffect="non-scaling-stroke"
                        />
                        <path
                            className="TransformationsPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                    <span className="TransformationsPreview__footer TransformationsPreview__swap">
                        <span className="TransformationsPreview__when-off">
                            2 transformations on. 4.1k events dropped.
                        </span>
                        <span className="TransformationsPreview__when-on">
                            3 transformations on. 4.1k events dropped.
                        </span>
                    </span>
                </div>
            </div>
        </div>
    )
}
