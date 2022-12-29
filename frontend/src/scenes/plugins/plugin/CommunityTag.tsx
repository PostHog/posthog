import { Tag } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'

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
