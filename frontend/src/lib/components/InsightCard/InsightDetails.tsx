import React from 'react'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { InsightModel } from '~/types'
import { ProfilePicture } from '../ProfilePicture'
import { TZLabel } from '../TimezoneAware'

function InsightDetailsInternal({ insight }: { insight: InsightModel }, ref: React.Ref<HTMLDivElement>): JSX.Element {
    const { filters, created_at, created_by } = insight

    return (
        <div className="InsightDetails" ref={ref}>
            <h5>Query summary</h5>
            <section className="InsightDetails__query">X</section>
            <h5>Filters</h5>
            <section className="InsightDetails__filters">X</section>
            <div className="InsightDetails__footer">
                <div>
                    <h5>Created by</h5>
                    <section>
                        <ProfilePicture name={created_by?.first_name} email={created_by?.email} showName size="md" />{' '}
                        <TZLabel time={created_at} />
                    </section>
                </div>
                {filters.breakdown && (
                    <div>
                        <h5>Breakdown by</h5>
                        <BreakdownFilter filters={filters} />
                    </div>
                )}
            </div>
        </div>
    )
}
export const InsightDetails = React.forwardRef(InsightDetailsInternal)
