import { LemonCollapse } from '@posthog/lemon-ui'

import { RelatedGroups } from 'scenes/groups/RelatedGroups'

interface RelatedGroupsPanelProps {
    personUuid: string
}

export function RelatedGroupsPanel({ personUuid }: RelatedGroupsPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="related-groups"
            panels={[
                {
                    key: 'related-groups',
                    header: 'Related groups',
                    content: <RelatedGroups id={personUuid} groupTypeIndex={null} embedded />,
                },
            ]}
        />
    )
}
