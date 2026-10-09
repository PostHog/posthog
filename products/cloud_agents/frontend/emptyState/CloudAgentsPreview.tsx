import './CloudAgentsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the empty state: a list of runs and the cost card of the selected run.
 * Two hidden radio inputs hold the selection and `:checked ~` styles swap the card, so the preview
 * needs no state and no timers. The two cards share one grid cell, so a swap does not move the layout.
 */
export function CloudAgentsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('CloudAgentsPreview', isStatic && 'CloudAgentsPreview--static')}>
            <input
                type="radio"
                name="cloud-agents-preview-run"
                id="cloud-agents-preview-run-a"
                className="CloudAgentsPreview__radio CloudAgentsPreview__radio--a"
                defaultChecked
            />
            <input
                type="radio"
                name="cloud-agents-preview-run"
                id="cloud-agents-preview-run-b"
                className="CloudAgentsPreview__radio CloudAgentsPreview__radio--b"
            />

            <div className="CloudAgentsPreview__panel">
                <div className="CloudAgentsPreview__head">
                    <span className="CloudAgentsPreview__title">Runs</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <label
                    htmlFor="cloud-agents-preview-run-a"
                    className="CloudAgentsPreview__row CloudAgentsPreview__row--a"
                >
                    <span className="CloudAgentsPreview__dot CloudAgentsPreview__dot--running" aria-hidden="true" />
                    <span className="CloudAgentsPreview__prompt">Add a dark mode toggle to settings</span>
                    <span className="CloudAgentsPreview__cost">$0.07</span>
                </label>
                <label
                    htmlFor="cloud-agents-preview-run-b"
                    className="CloudAgentsPreview__row CloudAgentsPreview__row--b"
                >
                    <span className="CloudAgentsPreview__dot CloudAgentsPreview__dot--done" aria-hidden="true" />
                    <span className="CloudAgentsPreview__prompt">Fix the flaky checkout test</span>
                    <span className="CloudAgentsPreview__cost">$0.31</span>
                </label>
                <div className="CloudAgentsPreview__hint">Select a run to see what it cost.</div>
            </div>

            <div className="CloudAgentsPreview__panel CloudAgentsPreview__swap">
                <div className="CloudAgentsPreview__card CloudAgentsPreview__card--a">
                    <div className="CloudAgentsPreview__head">
                        <span className="CloudAgentsPreview__title">Running for 11 minutes</span>
                        <span className="CloudAgentsPreview__status">acme/web</span>
                    </div>
                    <dl className="CloudAgentsPreview__costs">
                        <dt>Compute</dt>
                        <dd>$0.07</dd>
                        <dt>Model usage</dt>
                        <dd>Your subscription</dd>
                        <dt>Total so far</dt>
                        <dd className="CloudAgentsPreview__total">$0.07</dd>
                    </dl>
                </div>
                <div className="CloudAgentsPreview__card CloudAgentsPreview__card--b">
                    <div className="CloudAgentsPreview__head">
                        <span className="CloudAgentsPreview__title">Pull request opened</span>
                        <span className="CloudAgentsPreview__status">acme/web</span>
                    </div>
                    <dl className="CloudAgentsPreview__costs">
                        <dt>Compute</dt>
                        <dd>$0.12</dd>
                        <dt>Model usage</dt>
                        <dd>$0.19</dd>
                        <dt>Total</dt>
                        <dd className="CloudAgentsPreview__total">$0.31</dd>
                    </dl>
                </div>
            </div>
        </div>
    )
}
