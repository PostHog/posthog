import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Tag } from 'antd'

export function CommunityTag({ isCommunity, noun = 'app' }: { isCommunity?: boolean; noun?: string }): JSX.Element {
    return (
        <Tooltip
            title={
                isCommunity
                    ? `This ${noun} was built by a community member, not the PostHog team.`
                    : `This ${noun} was built by the PostHog team.`
            }
        >
            <Tag color={isCommunity ? 'cyan' : 'geekblue'}>{isCommunity ? 'Community' : 'Official'}</Tag>
        </Tooltip>
    )
}
