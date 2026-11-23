import { Heading, Text } from '@posthog/quill'

import { MEMBER_JOIN_DESCRIPTION } from './emailPreferencesCopy'

export function QuillMemberJoinHeading(): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Heading size="sm" render={<h3 className="m-0" />}>
                New member joined
            </Heading>
            <Text size="xs" variant="muted" className="m-0">
                {MEMBER_JOIN_DESCRIPTION}
            </Text>
        </div>
    )
}
