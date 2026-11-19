import { AvatarGroup, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'

interface QuillPeopleAvatarsProps {
    people: { name: string; email: string }[]
    limit?: number
}

export function QuillPeopleAvatars({ people, limit = 3 }: QuillPeopleAvatarsProps): JSX.Element | null {
    if (!people.length) {
        return null
    }
    const overflow = people.length - limit

    return (
        <Tooltip>
            <TooltipTrigger
                delay={200}
                render={<span className="ph-no-capture inline-flex items-center gap-1" tabIndex={0} />}
            >
                <AvatarGroup stacked size="xs">
                    {people.slice(0, limit).map((person) => (
                        <QuillPersonAvatar key={person.email} name={person.name} email={person.email} size="xs" />
                    ))}
                </AvatarGroup>
                {overflow > 0 && (
                    <Text size="xs" variant="muted" render={<span />}>
                        +{overflow}
                    </Text>
                )}
            </TooltipTrigger>
            <TooltipContent className="ph-no-capture">
                {people.map((person) => person.name || person.email).join(', ')}
            </TooltipContent>
        </Tooltip>
    )
}
