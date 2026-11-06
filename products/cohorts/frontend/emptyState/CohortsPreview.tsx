import './CohortsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the cohorts empty state: a cohort definition and the
 * people it matches. Adding the second condition narrows the definition, and the
 * matched count and the people list follow. One hidden checkbox drives it all via
 * `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Before/after pairs are stacked in `__swap`
 * grids and crossfaded, so nothing shifts.
 */
export function CohortsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('CohortPreview', isStatic && 'CohortPreview--static')}>
            {/* Narrowed state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="cohort-preview-narrow" className="CohortPreview__checkbox" />

            <div className="CohortPreview__panel">
                <div className="CohortPreview__head">
                    <span className="CohortPreview__title">Trial users who saw pricing</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="CohortPreview__conditions">
                    <div className="CohortPreview__condition">
                        <span className="CohortPreview__match-tag">Match</span>
                        <span className="CohortPreview__condition-text">
                            Signed up in the last <strong>30 days</strong>
                        </span>
                    </div>

                    {/* Reserved slot: the second condition fades in over a spacer of the
                        same height, so the card never changes size. */}
                    <div className="CohortPreview__condition-slot CohortPreview__swap">
                        <span className="CohortPreview__condition-spacer CohortPreview__when-before" />
                        <div className="CohortPreview__condition CohortPreview__condition--new CohortPreview__when-after">
                            <span className="CohortPreview__match-tag">And</span>
                            <span className="CohortPreview__condition-text">
                                Viewed <strong>/pricing</strong> at least once
                            </span>
                        </div>
                    </div>

                    <label htmlFor="cohort-preview-narrow" className="CohortPreview__add">
                        <span className="CohortPreview__swap">
                            <span className="CohortPreview__when-before">Add condition</span>
                            <span className="CohortPreview__when-after">Remove condition</span>
                        </span>
                    </label>
                </div>

                <div className="CohortPreview__count-row">
                    <span className="CohortPreview__count-label">People matched</span>
                    <span className="CohortPreview__count CohortPreview__swap">
                        <span className="CohortPreview__when-before">8,412</span>
                        <span className="CohortPreview__count--narrowed CohortPreview__when-after">1,197</span>
                    </span>
                </div>
            </div>

            <div className="CohortPreview__panel">
                <div className="CohortPreview__head">
                    <span className="CohortPreview__title">People</span>
                    <span className="CohortPreview__live" aria-hidden="true" />
                </div>

                <div className="CohortPreview__rows">
                    <div className="CohortPreview__row">
                        <span className="CohortPreview__avatar CohortPreview__avatar--a" aria-hidden="true">
                            AR
                        </span>
                        <span className="CohortPreview__person">avery@example.com</span>
                        <span className="CohortPreview__meta CohortPreview__swap">
                            <span className="CohortPreview__when-before">Signed up 4d ago</span>
                            <span className="CohortPreview__when-after">Viewed /pricing 2d ago</span>
                        </span>
                    </div>
                    <div className="CohortPreview__row">
                        <span className="CohortPreview__avatar CohortPreview__avatar--b" aria-hidden="true">
                            JM
                        </span>
                        <span className="CohortPreview__person">jordan@example.com</span>
                        <span className="CohortPreview__meta CohortPreview__swap">
                            <span className="CohortPreview__when-before">Signed up 9d ago</span>
                            <span className="CohortPreview__when-after">Viewed /pricing 6d ago</span>
                        </span>
                    </div>
                    <div className="CohortPreview__row">
                        <span className="CohortPreview__avatar CohortPreview__avatar--c" aria-hidden="true">
                            SK
                        </span>
                        <span className="CohortPreview__person">sam@example.com</span>
                        <span className="CohortPreview__meta CohortPreview__swap">
                            <span className="CohortPreview__when-before">Signed up 21d ago</span>
                            <span className="CohortPreview__when-after">Viewed /pricing 11d ago</span>
                        </span>
                    </div>
                </div>

                <div className="CohortPreview__hint CohortPreview__swap">
                    <span className="CohortPreview__when-before">Add a condition to narrow the group.</span>
                    <span className="CohortPreview__when-after">
                        Reuse this cohort as a filter, a flag target, or a survey audience.
                    </span>
                </div>
            </div>
        </div>
    )
}
