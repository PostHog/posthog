import { IconExternal } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia } from '@posthog/quill'

import { DomainConnectProviderName } from '~/queries/schema/schema-general'

export function QuillDomainConnectBanner({
    providerName,
    providerLogo,
    onConfigure,
    className,
}: {
    providerName: DomainConnectProviderName
    providerLogo: JSX.Element
    onConfigure: () => void
    className?: string
}): JSX.Element {
    return (
        <Item tone="info" size="sm" className={className}>
            <ItemMedia>{providerLogo}</ItemMedia>
            <ItemContent>
                <ItemDescription>
                    Your DNS is managed by <strong>{providerName}</strong>, which supports automatic configuration.
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="primary" onClick={onConfigure}>
                    <IconExternal />
                    Configure automatically
                </Button>
            </ItemActions>
        </Item>
    )
}
