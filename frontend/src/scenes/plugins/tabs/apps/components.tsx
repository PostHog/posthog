import { PluginType } from '~/types'
import { LemonTag } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function RepositoryTag({ plugin }: { plugin: Pick<PluginType, 'maintainer' | 'url'> }): JSX.Element {
    const isOfficial = plugin.maintainer === 'official'
    return (
        <Tooltip
            title={
                !isOfficial
                    ? `This app was built by a community member, not the PostHog team.`
                    : `This app was built by the PostHog team.`
            }
        >
            <LemonTag type={isOfficial ? 'primary' : 'highlight'}>{isOfficial ? 'Official' : 'Community'}</LemonTag>
        </Tooltip>
    )
}
