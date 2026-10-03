import type { SignalReportSectionsApi } from 'products/signals/frontend/generated/api.schemas'
import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { conciseText } from './todayProse'

const CODE_PATH = /`[^`]*[/.][^`]*`/
const PROPOSAL_CHARS = 260
const IMPACT_CHARS = 180

function mentionsCodePath(markdown: string): boolean {
    return CODE_PATH.test(markdown)
}

export function reportProposal(report: SignalReport, sections: Pick<SignalReportSectionsApi, 'solution'>): string {
    return conciseText(
        sections.solution ?? (isActionCapableReport(report) ? report.suggested_prompts?.[0] : null),
        PROPOSAL_CHARS
    )
}

export function impactSentence(sections: Pick<SignalReportSectionsApi, 'impact'>): string {
    const text = conciseText(sections.impact, IMPACT_CHARS)
    const statesMeasurement = /\d/.test(text) && !mentionsCodePath(text)
    return statesMeasurement ? text : ''
}
