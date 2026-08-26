import type { Meta, StoryObj } from '@storybook/react'
import { useRef } from 'react'

import { IconQuestion } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import type { ChatMessage } from '../../types'
import { Message } from './Message'
import { useQuestionHighlight } from './useQuestionHighlight'

// The reading aid for tickets that arrive as one unformatted block: the customer's questions are
// tinted so the ask is findable without re-reading the whole thing. Our own reply keeps its
// question plain, which is the distinction worth seeing side by side.

const CUSTOMER_MESSAGE: ChatMessage = {
    id: 'customer',
    authorType: 'customer',
    authorName: 'Testy McTestface',
    createdAt: '2026-07-25T09:12:00Z',
    content:
        "hello from example.com, sorry in advance for the wall of text. we put the snippet on our marketing site last friday and events did start arriving, then on monday morning everything went quiet. nothing changed on our end as far as i can tell, the snippet is still in the head tag and the network tab shows the requests going out with a 200. is there a rate limit on the free plan that we might have hit? we send maybe 40k events a month so i wouldn't have thought so. separately, our staging site reports into the same project, which i now suspect is wrong. should staging have a project of its own, or is there a tidier way to keep the two apart? last thing while i'm here, every person profile shows as anonymous even though we call identify straight after login. thanks for any pointers.",
}

// A second customer message on the rich-content path. Both renderers are worth showing, because the
// highlight reads their rendered text nodes rather than either source format.
const RICH_CUSTOMER_MESSAGE: ChatMessage = {
    id: 'customer-rich',
    authorType: 'customer',
    authorName: 'Testy McTestface',
    createdAt: '2026-07-25T09:31:00Z',
    content: 'One more thing. Does the fix need a redeploy, or does it pick up on its own?',
    richContent: {
        type: 'doc',
        content: [
            {
                type: 'paragraph',
                content: [
                    { type: 'text', text: 'One more thing. Does the fix need a ' },
                    { type: 'text', marks: [{ type: 'bold' }], text: 'redeploy' },
                    { type: 'text', text: ', or does it pick up on its own?' },
                ],
            },
        ],
    },
}

const TEAM_MESSAGE: ChatMessage = {
    id: 'team',
    authorType: 'human',
    authorName: 'Sample Supportperson',
    createdAt: '2026-07-25T10:04:00Z',
    content: 'Thanks for all the detail. Nothing on your account is rate limited. Can you send me the project ID?',
}

function Thread({ highlighted }: { highlighted: boolean }): JSX.Element {
    const panelRef = useRef<HTMLDivElement>(null)
    useQuestionHighlight(panelRef, highlighted)

    return (
        <div ref={panelRef} className="max-w-2xl">
            <LemonCard hoverEffect={false} className="flex flex-col p-3">
                <div className="flex justify-end pb-2">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconQuestion />}
                        active={highlighted}
                        tooltip="Highlight questions in customer messages"
                    >
                        Highlight questions
                    </LemonButton>
                </div>
                <Message message={CUSTOMER_MESSAGE} isCustomer />
                <Message message={RICH_CUSTOMER_MESSAGE} isCustomer />
                <Message message={TEAM_MESSAGE} isCustomer={false} />
            </LemonCard>
        </div>
    )
}

const meta: Meta<typeof Thread> = {
    title: 'Scenes-App/Support/QuestionHighlight',
    component: Thread,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-07-25 12:00:00' },
}
export default meta

type Story = StoryObj<typeof Thread>

export const Off: Story = { render: () => <Thread highlighted={false} /> }

export const On: Story = { render: () => <Thread highlighted /> }
