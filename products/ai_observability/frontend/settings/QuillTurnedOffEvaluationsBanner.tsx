import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillTurnedOffEvaluationsBanner({
    message,
    actionLabel,
    loading,
    onTurnBackOn,
}: {
    message: string
    actionLabel: string
    loading: boolean
    onTurnBackOn: () => void
}): JSX.Element {
    return (
        <Item tone="info" size="sm" className="flex-wrap">
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="outline"
                    onClick={onTurnBackOn}
                    loading={loading}
                    data-attr="llma-provider-key-turn-evaluations-back-on"
                >
                    {actionLabel}
                </Button>
            </ItemActions>
        </Item>
    )
}
