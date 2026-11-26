import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillWebAndApiAccessSummary({
    domainsSummary,
    secretSummary,
    onManage,
}: {
    domainsSummary: string
    secretSummary: string | null
    onManage: () => void
}): JSX.Element {
    return (
        <Item tone="info" size="sm">
            <ItemContent>
                <ItemDescription>
                    <span>{domainsSummary}</span>{' '}
                    {secretSummary && (
                        <>
                            <span>{secretSummary}</span>{' '}
                        </>
                    )}
                    <span>These settings apply to the widget and the Direct API.</span>
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onManage} data-attr="support-web-and-api-access-manage">
                    Manage
                </Button>
            </ItemActions>
        </Item>
    )
}
