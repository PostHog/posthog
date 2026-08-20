import './LLMPromptPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored rising prompt-fetches series for the stat card sparkline.
const SPARK_LINE = 'M 0 31 L 10 29.5 L 20 30.2 L 30 27 L 40 27.8 L 50 24.5 L 60 25.4 L 70 21 L 80 19.5 L 90 16 L 100 14'
const SPARK_AREA = `${SPARK_LINE} L 100 40 L 0 40 Z`

/**
 * Example-data preview for the prompts empty state: one prompt's version history
 * wired to a mini runtime-fetch card, so promoting the newest version - by picking
 * its row - moves the production label and crossfades the text the app fetches,
 * with no deploy in sight. The whole interaction is two hidden radios driving
 * `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Version pairs are stacked in `__swap`
 * grids and crossfaded, so promoting never changes the layout's size.
 */
export function LLMPromptPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('PromptPreview', isStatic && 'PromptPreview--static')}>
            {/* Served-version state, before all three cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="prompt-preview-version"
                id="prompt-preview-v3"
                defaultChecked
                className="PromptPreview__radio"
            />
            <input type="radio" name="prompt-preview-version" id="prompt-preview-v4" className="PromptPreview__radio" />

            <div className="PromptPreview__panel">
                <div className="PromptPreview__head">
                    <span className="PromptPreview__name">support-triage</span>
                    <span className="PromptPreview__versions">3 versions</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="PromptPreview__rows">
                    <label htmlFor="prompt-preview-v4" className="PromptPreview__row PromptPreview__row--v4">
                        <span className="PromptPreview__vradio PromptPreview__vradio--v4" aria-hidden="true" />
                        <span className="PromptPreview__version">v4</span>
                        <span className="PromptPreview__message">Add refund policy context</span>
                        <span className="PromptPreview__chip-slot PromptPreview__swap">
                            <span className="PromptPreview__chip PromptPreview__when-v4">production</span>
                        </span>
                    </label>
                    <label htmlFor="prompt-preview-v3" className="PromptPreview__row PromptPreview__row--v3">
                        <span className="PromptPreview__vradio PromptPreview__vradio--v3" aria-hidden="true" />
                        <span className="PromptPreview__version">v3</span>
                        <span className="PromptPreview__message">Tighten tone guidelines</span>
                        <span className="PromptPreview__chip-slot PromptPreview__swap">
                            <span className="PromptPreview__chip PromptPreview__when-v3">production</span>
                        </span>
                    </label>
                    <div className="PromptPreview__row PromptPreview__row--past">
                        <span className="PromptPreview__vradio PromptPreview__vradio--past" aria-hidden="true" />
                        <span className="PromptPreview__version">v2</span>
                        <span className="PromptPreview__message">Initial prompt</span>
                        <span className="PromptPreview__chip-slot" />
                    </div>
                </div>

                <div className="PromptPreview__hint PromptPreview__swap">
                    <span className="PromptPreview__when-v3">Pick v4 to move the production label to it.</span>
                    <span className="PromptPreview__when-v4">v4 is live everywhere. No redeploy.</span>
                </div>
            </div>

            <div className="PromptPreview__code">
                <div className="PromptPreview__code-head">
                    <span className="PromptPreview__code-dot" />
                    <span className="PromptPreview__code-dot" />
                    <span className="PromptPreview__code-dot" />
                    <span className="PromptPreview__code-file">app/support.ts</span>
                </div>
                <div className="PromptPreview__code-body">
                    <div className="PromptPreview__code-line">
                        <span className="PromptPreview__kw">const</span> prompt ={' '}
                        <span className="PromptPreview__kw">await</span> posthog.
                        <span className="PromptPreview__fn">getPrompt</span>(
                        <span className="PromptPreview__str">'support-triage'</span>, {'{'} label:{' '}
                        <span className="PromptPreview__str">'production'</span> {'}'})
                    </div>
                    <div className="PromptPreview__fetched PromptPreview__swap">
                        <span className="PromptPreview__fetched-body PromptPreview__when-v3">
                            <span className="PromptPreview__fetched-version">v3</span>
                            <span className="PromptPreview__fetched-text">
                                You are a support agent for Hedgebox. Keep replies short and friendly.
                            </span>
                        </span>
                        <span className="PromptPreview__fetched-body PromptPreview__when-v4">
                            <span className="PromptPreview__fetched-version PromptPreview__fetched-version--live">
                                v4
                            </span>
                            <span className="PromptPreview__fetched-text">
                                You are a support agent for Hedgebox. Include the refund policy when relevant.
                            </span>
                        </span>
                    </div>
                </div>
            </div>

            <div className="PromptPreview__spark">
                <div className="PromptPreview__spark-head">
                    <span className="PromptPreview__spark-title">Prompt fetches · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="PromptPreview__spark-value">
                    8,412
                    <span className="PromptPreview__spark-label PromptPreview__swap">
                        <span className="PromptPreview__when-v3">serving v3</span>
                        <span className="PromptPreview__spark-label--live PromptPreview__when-v4">serving v4</span>
                    </span>
                </div>

                <div className="PromptPreview__spark-chart">
                    <svg
                        className="PromptPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="PromptPreview__spark-area" d={SPARK_AREA} />
                        <path className="PromptPreview__spark-line" d={SPARK_LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="PromptPreview__spark-trace"
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
