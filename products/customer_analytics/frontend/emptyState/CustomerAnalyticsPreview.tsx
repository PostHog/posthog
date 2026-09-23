import './CustomerAnalyticsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the customer analytics empty state: an accounts list
 * and one account's detail. Clicking the flagged account opens its detail card.
 * One hidden checkbox drives it via `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill. Detail
 * states crossfade in `__swap` grids, so nothing shifts.
 */
export function CustomerAnalyticsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('CustomerPreview', isStatic && 'CustomerPreview--static')}>
            {/* Selection state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="customer-preview-select" className="CustomerPreview__checkbox" />

            <div className="CustomerPreview__accounts">
                <div className="CustomerPreview__head">
                    <span className="CustomerPreview__title">
                        <span className="CustomerPreview__live-dot" aria-hidden="true" />
                        Accounts
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="CustomerPreview__rows">
                    <label
                        htmlFor="customer-preview-select"
                        className="CustomerPreview__row CustomerPreview__row--hero"
                    >
                        <span className="CustomerPreview__account">Miller & Sons</span>
                        <span className="CustomerPreview__meta">scale · 42 users</span>
                        <span className="CustomerPreview__health CustomerPreview__health--falling">activity ↓ 31%</span>
                    </label>
                    <div className="CustomerPreview__row">
                        <span className="CustomerPreview__account">Fresh Greens Co</span>
                        <span className="CustomerPreview__meta">startup · 7 users</span>
                        <span className="CustomerPreview__health">activity ↑ 12%</span>
                    </div>
                    <div className="CustomerPreview__row">
                        <span className="CustomerPreview__account">Night Owl Labs</span>
                        <span className="CustomerPreview__meta">free · 3 users</span>
                        <span className="CustomerPreview__health">activity ↑ 4%</span>
                    </div>
                </div>
                <div className="CustomerPreview__hint CustomerPreview__swap">
                    <span className="CustomerPreview__when-idle">Click the account that's cooling off.</span>
                    <span className="CustomerPreview__when-selected">
                        Usage is falling ahead of the renewal. Click again to close.
                    </span>
                </div>
            </div>

            <div className="CustomerPreview__detail">
                <div className="CustomerPreview__head">
                    <span className="CustomerPreview__title">Account detail</span>
                    <span className="CustomerPreview__fresh CustomerPreview__when-selected">Miller & Sons</span>
                </div>
                <div className="CustomerPreview__detail-body CustomerPreview__swap">
                    <div className="CustomerPreview__detail-hint CustomerPreview__when-idle">
                        Select an account to see the people and activity behind it.
                    </div>
                    <div className="CustomerPreview__facts CustomerPreview__when-selected">
                        <div className="CustomerPreview__fact">
                            <span className="CustomerPreview__fact-key">Weekly active users</span>
                            <span className="CustomerPreview__fact-val">18 → 11</span>
                        </div>
                        <div className="CustomerPreview__fact">
                            <span className="CustomerPreview__fact-key">Last seen</span>
                            <span className="CustomerPreview__fact-val">2 days ago · dashboard</span>
                        </div>
                        <div className="CustomerPreview__fact">
                            <span className="CustomerPreview__fact-key">Open feature requests</span>
                            <span className="CustomerPreview__fact-val">3 · latest: SSO support</span>
                        </div>
                        <div className="CustomerPreview__fact">
                            <span className="CustomerPreview__fact-key">Notes</span>
                            <span className="CustomerPreview__fact-val">"Renewal call booked for next week"</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
