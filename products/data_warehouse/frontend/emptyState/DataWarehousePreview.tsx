import './DataWarehousePreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the data warehouse empty state: synced sources and a
 * SQL join over them. Clicking "Run" fills the results with events joined to
 * Stripe customers. One hidden checkbox drives it via `:checked ~` styles - no
 * timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Idle/run pairs are stacked in `__swap` grids, so nothing shifts.
 */
export function DataWarehousePreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('WarehousePreview', isStatic && 'WarehousePreview--static')}>
            {/* Run state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="warehouse-preview-run" className="WarehousePreview__checkbox" />

            <div className="WarehousePreview__sources">
                <div className="WarehousePreview__head">
                    <span className="WarehousePreview__title">Sources</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="WarehousePreview__rows">
                    <div className="WarehousePreview__row">
                        <span className="WarehousePreview__source-name">Stripe</span>
                        <span className="WarehousePreview__source-meta">12 tables · synced 5 min ago</span>
                        <span className="WarehousePreview__badge WarehousePreview__badge--synced">synced</span>
                    </div>
                    <div className="WarehousePreview__row">
                        <span className="WarehousePreview__source-name">Postgres</span>
                        <span className="WarehousePreview__source-meta">orders, customers, invoices…</span>
                        <span className="WarehousePreview__badge WarehousePreview__badge--syncing">
                            <span className="WarehousePreview__sync-spinner" aria-hidden="true" />
                            syncing
                        </span>
                    </div>
                </div>
            </div>

            <div className="WarehousePreview__sql">
                <div className="WarehousePreview__head">
                    <span className="WarehousePreview__title">SQL</span>
                    <label htmlFor="warehouse-preview-run" className="WarehousePreview__run">
                        <span className="WarehousePreview__swap">
                            <span className="WarehousePreview__when-idle">▶ Run</span>
                            <span className="WarehousePreview__when-run">Ran in 0.4 s</span>
                        </span>
                    </label>
                </div>
                <pre className="WarehousePreview__query">
                    {`SELECT plan, count() AS signups
FROM events
JOIN stripe_customers ON email = person.properties.email
WHERE event = 'signed_up'
GROUP BY plan`}
                </pre>
                <div className="WarehousePreview__results WarehousePreview__swap">
                    <div className="WarehousePreview__results-hint WarehousePreview__when-idle">
                        Run the query to join your events with Stripe.
                    </div>
                    <div className="WarehousePreview__table WarehousePreview__when-run">
                        <div className="WarehousePreview__tr WarehousePreview__tr--head">
                            <span>plan</span>
                            <span>signups</span>
                        </div>
                        <div className="WarehousePreview__tr">
                            <span>scale</span>
                            <span>128</span>
                        </div>
                        <div className="WarehousePreview__tr">
                            <span>startup</span>
                            <span>342</span>
                        </div>
                        <div className="WarehousePreview__tr">
                            <span>free</span>
                            <span>1,904</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
