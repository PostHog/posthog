import { Button } from '@posthog/quill'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { MatchingActorsLinkProps } from './MatchingActorsLink'
import { matchingActorsUrl } from './matchingActorsUrl'

export function QuillMatchingActorsLink({
    properties,
    resolvedGroupTypeIndex,
    targetName,
}: MatchingActorsLinkProps): JSX.Element {
    return (
        <Button
            variant="link"
            size="inline"
            className="w-fit"
            nativeButton={false}
            render={<LinkPrimitive to={matchingActorsUrl(properties, resolvedGroupTypeIndex)} target="_blank" />}
        >
            <span>{`View matching ${targetName}`}</span>
            <IconOpenInNew />
        </Button>
    )
}
