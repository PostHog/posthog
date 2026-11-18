import { LazyLemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LazyLemonMarkdown'

import { HumanizedActivityLogItem } from './humanizeActivity'

export function ActivityLogDescription({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    return logItem.markdownDescription ? (
        <LazyLemonMarkdown>{logItem.markdownDescription}</LazyLemonMarkdown>
    ) : (
        <>{logItem.description}</>
    )
}
