import { IconWarning } from '@posthog/icons'
import { Button, Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { FeatureFlagBasicType } from '~/types'

import type { ExperimentWarning } from '../experimentLogic'
import { WarningDetail, warningCaption } from './ExperimentWarningDetail'

export function QuillExperimentWarningBanner({
    warning,
    flag,
    onOpenFlag,
}: {
    warning: ExperimentWarning
    flag: FeatureFlagBasicType | null
    onOpenFlag: () => void
}): JSX.Element {
    const flagLink = flag ? (
        <Button
            variant="link"
            size="inline"
            nativeButton={false}
            render={<LinkPrimitive to={urls.featureFlag(flag.id)} target="_blank" onClick={onOpenFlag} />}
        >
            {flag.key}
        </Button>
    ) : null

    return (
        <Item variant="outline" size="sm" tone="warning" className="mb-4" data-attr="experiment-warning-banner">
            <ItemMedia variant="icon" aria-hidden>
                <IconWarning />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle>{warningCaption(warning.key)}</ItemTitle>
                <ItemDescription>
                    <WarningDetail warning={warning} flagLink={flagLink} />
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
