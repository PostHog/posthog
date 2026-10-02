import { Text } from '@posthog/quill'

import { TodayReportSections } from './todayReportPresentation'
import { TodayReportProse } from './TodayReportProse'

export function TodayReportProposal({ sections }: { sections: TodayReportSections }): JSX.Element | null {
    if (!sections.proposal && !sections.expected) {
        return null
    }
    return (
        <section className="flex flex-col gap-2" data-attr="today-report-proposal">
            <Text size="sm" render={<h2 />} className="font-semibold">
                Proposal
            </Text>
            {sections.proposal && <TodayReportProse markdown={sections.proposal} tone="body" />}
            {sections.expected && <TodayReportProse markdown={`**Expected:** ${sections.expected}`} tone="body" />}
        </section>
    )
}
