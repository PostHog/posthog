import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Popover } from 'lib/lemon-ui/Popover'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'

/**
 * Discuss opens a small popover with a textarea so the user poses their question up front, then kicks
 * off a fresh research task whose prompt is the report link (for the agent to open and read) followed
 * by that question. Discuss never changes the report's state, so it stays available for every report –
 * including resolved and archived ones.
 */
export function DiscussReportButton({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing } = useValues(inboxTaskKickoffLogic)
    const { discussReport } = useActions(inboxTaskKickoffLogic)
    const [isOpen, setIsOpen] = useState(false)
    const [question, setQuestion] = useState('')

    const submit = (): void => {
        const trimmed = question.trim()
        if (!trimmed) {
            return
        }
        captureInboxReportAction({ report, actionType: 'discuss', surface: 'detail_pane' })
        discussReport(report, reportUrl, trimmed)
        setIsOpen(false)
        setQuestion('')
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="flex flex-col gap-2 p-2 w-[22rem]">
                    <LemonTextArea
                        value={question}
                        onChange={setQuestion}
                        onPressEnter={submit}
                        placeholder="What would you like to discuss about this report?"
                        maxLength={4000}
                        rows={4}
                        autoFocus
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={submit}
                            loading={isDiscussing}
                            disabledReason={question.trim() ? undefined : 'Enter a question first'}
                        >
                            Discuss
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconMessage />}
                onClick={() => setIsOpen((open) => !open)}
                tooltip="Ask an agent about this report"
            >
                Discuss
            </LemonButton>
        </Popover>
    )
}
