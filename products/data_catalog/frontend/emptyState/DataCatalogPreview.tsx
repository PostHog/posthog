import './DataCatalogPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored weekly series for the metric being reviewed.
const LINE = 'M 0 26 L 14 24 L 28 27 L 42 20 L 56 22 L 70 15 L 84 13 L 100 8'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the data catalog empty state: a proposed metric and the
 * definition behind it. Approving it certifies the definition and points the queries
 * that use the number at it. One hidden checkbox drives it via `:checked ~` styles -
 * no timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Before/after pairs share a `__swap` grid cell and crossfade, so no row moves.
 */
export function DataCatalogPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('CatalogPreview', isStatic && 'CatalogPreview--static')}>
            {/* Approved state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="catalog-preview-approve" className="CatalogPreview__checkbox" />

            <div className="CatalogPreview__panel">
                <div className="CatalogPreview__head">
                    <span className="CatalogPreview__title">Metrics</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="CatalogPreview__rows">
                    <div className="CatalogPreview__row">
                        <span className="CatalogPreview__name">revenue</span>
                        <span className="CatalogPreview__unit">USD</span>
                        <span className="CatalogPreview__pill CatalogPreview__pill--approved">Approved</span>
                    </div>

                    <label htmlFor="catalog-preview-approve" className="CatalogPreview__row CatalogPreview__row--focus">
                        <span className="CatalogPreview__name">active_users</span>
                        <span className="CatalogPreview__unit">people</span>
                        <span className="CatalogPreview__state CatalogPreview__swap">
                            <span className="CatalogPreview__pill CatalogPreview__when-before">Proposed</span>
                            <span className="CatalogPreview__pill CatalogPreview__pill--approved CatalogPreview__when-after">
                                Approved
                            </span>
                        </span>
                    </label>

                    <div className="CatalogPreview__row">
                        <span className="CatalogPreview__name">signups</span>
                        <span className="CatalogPreview__unit">people</span>
                        <span className="CatalogPreview__pill CatalogPreview__pill--approved">Approved</span>
                    </div>
                </div>
            </div>

            <div className="CatalogPreview__definition">
                <div className="CatalogPreview__head">
                    <span className="CatalogPreview__title">active_users</span>
                    <span className="CatalogPreview__spark-value">4,182</span>
                </div>

                <div className="CatalogPreview__body">
                    <p className="CatalogPreview__desc">People with at least one event in the last 7 days.</p>

                    <svg
                        className="CatalogPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="CatalogPreview__spark-area" d={areaPath(LINE)} />
                        <path className="CatalogPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="CatalogPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>

                    <span className="CatalogPreview__footer CatalogPreview__swap">
                        <span className="CatalogPreview__when-before">
                            Proposed 2 days ago. Click the row above to approve it.
                        </span>
                        <span className="CatalogPreview__when-after">
                            Approved. 12 insights and every SQL query now read this definition.
                        </span>
                    </span>
                </div>
            </div>
        </div>
    )
}
