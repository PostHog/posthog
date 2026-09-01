import './AnnotationsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored weekly sign-up series with a visible dip two thirds along, which is
// the moment the annotation explains.
const LINE = 'M 0 18 L 14 15 L 28 17 L 42 13 L 56 14 L 66 31 L 80 28 L 100 24'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the annotations empty state: a chart with an unexplained
 * dip, and the note that explains it. Clicking the marker pins the annotation - the
 * flag lands on the dip, the note opens, and the row joins the list below. One hidden
 * checkbox drives it all via `:checked ~` styles - no timers or state, per the preview
 * rules in the `building-product-empty-states` skill. Before/after pairs are stacked
 * in `__swap` grids and crossfaded, so nothing shifts.
 */
export function AnnotationsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('AnnotationPreview', isStatic && 'AnnotationPreview--static')}>
            {/* Annotated state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="annotation-preview-add" className="AnnotationPreview__checkbox" />

            <div className="AnnotationPreview__chart">
                <div className="AnnotationPreview__head">
                    <span className="AnnotationPreview__title">Weekly sign-ups</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="AnnotationPreview__plot">
                    <svg
                        className="AnnotationPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="AnnotationPreview__spark-area" d={areaPath(LINE)} />
                        <path className="AnnotationPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="AnnotationPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                        <line
                            className="AnnotationPreview__marker-line"
                            x1="66"
                            x2="66"
                            y1="0"
                            y2="40"
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>

                    {/* Sits over the dip, at the same x as the marker line. */}
                    <label htmlFor="annotation-preview-add" className="AnnotationPreview__marker">
                        <span className="AnnotationPreview__marker-dot" aria-hidden="true" />
                    </label>

                    <div className="AnnotationPreview__note AnnotationPreview__swap">
                        <span className="AnnotationPreview__when-before">Sign-ups dropped 38% this week</span>
                        <span className="AnnotationPreview__note-card AnnotationPreview__when-after">
                            <span className="AnnotationPreview__note-date">Mar 14</span>
                            Pricing page redesign shipped
                        </span>
                    </div>
                </div>

                <div className="AnnotationPreview__hint AnnotationPreview__swap">
                    <span className="AnnotationPreview__when-before">Click the marker to explain the drop.</span>
                    <span className="AnnotationPreview__when-after">
                        Every chart covering Mar 14 now shows this note. Click again to undo.
                    </span>
                </div>
            </div>

            <div className="AnnotationPreview__panel">
                <div className="AnnotationPreview__head">
                    <span className="AnnotationPreview__title">Annotations</span>
                </div>

                <div className="AnnotationPreview__rows">
                    {/* Reserved slot: the new row fades in over a spacer of the same
                        height, so the rows below never move. */}
                    <div className="AnnotationPreview__row-slot AnnotationPreview__swap">
                        <span className="AnnotationPreview__row-spacer AnnotationPreview__when-before" />
                        <div className="AnnotationPreview__row AnnotationPreview__row--new AnnotationPreview__when-after">
                            <span className="AnnotationPreview__flag" aria-hidden="true" />
                            <span className="AnnotationPreview__text">Pricing page redesign shipped</span>
                            <span className="AnnotationPreview__date">Mar 14</span>
                        </div>
                    </div>
                    <div className="AnnotationPreview__row">
                        <span className="AnnotationPreview__flag" aria-hidden="true" />
                        <span className="AnnotationPreview__text">Switched onboarding emails on</span>
                        <span className="AnnotationPreview__date">Mar 2</span>
                    </div>
                    <div className="AnnotationPreview__row">
                        <span className="AnnotationPreview__flag" aria-hidden="true" />
                        <span className="AnnotationPreview__text">Launched on Product Hunt</span>
                        <span className="AnnotationPreview__date">Feb 19</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
