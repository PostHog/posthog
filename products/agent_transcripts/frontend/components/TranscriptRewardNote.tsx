import { Highlight, Text } from '@posthog/quill'

/** The merch code offer. Only the experiment's `test` arm may render it. */
export function TranscriptRewardNote(): JSX.Element {
    return (
        <Text render={<p className="m-0" />} data-attr="agent-transcript-reward">
            When we approve your transcript, we email you{' '}
            <Highlight color="yellow">a $20 code for the PostHog merch store</Highlight>.
        </Text>
    )
}
