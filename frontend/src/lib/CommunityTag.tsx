import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export function CommunityTag({ isCommunity, noun = 'app' }: { isCommunity?: boolean; noun?: string }): JSX.Element {
    return (
        <Tooltip
            title={
                isCommunity
                    ? `This ${noun} was built by a community member, not the PostHog team.`
                    : `This ${noun} was built by the PostHog team.`
            }
        >
            <LemonTag type={isCommunity ? 'highlight' : 'primary'}>{isCommunity ? 'Community' : 'Official'}</LemonTag>
        </Tooltip>
    )
}
