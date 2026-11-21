import { IconArrowRight, IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import type { PathCleaningSuggestionIssueApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { QuillPathCleaningPreviewDialog } from './QuillPathCleaningPreviewDialog'

export function QuillPathCleaningSuggestionsBanner({
    suggestion,
    restrictedReason,
    applying,
    onApply,
    onDismiss,
    onPreview,
}: {
    suggestion: PathCleaningSuggestionIssueApi
    restrictedReason: string | null
    applying: boolean
    onApply: () => void
    onDismiss: () => void
    onPreview: () => void
}): JSX.Element {
    const ruleCount = suggestion.rules.length

    return (
        <>
            <Item tone="info" size="sm">
                <ItemContent className="gap-2">
                    <ItemDescription>
                        We analyzed your traffic and suggest <strong>{ruleCount}</strong> path cleaning{' '}
                        {ruleCount === 1 ? 'rule' : 'rules'} to group similar pages. Review and apply them:
                    </ItemDescription>
                    <div className="flex flex-col gap-1">
                        {suggestion.rules.map((rule) => (
                            <div key={rule.order} className="flex flex-wrap items-center gap-2 font-mono text-xs">
                                <code>{rule.regex}</code>
                                <IconArrowRight />
                                <code>{rule.alias}</code>
                                <span className="font-sans text-muted-foreground">
                                    groups {rule.match_count} of your top {suggestion.sampled_path_count} paths
                                </span>
                            </div>
                        ))}
                    </div>
                    <div>
                        <Button variant="outline" onClick={onPreview}>
                            Preview on your paths
                        </Button>
                    </div>
                </ItemContent>
                <ItemActions className="flex-wrap">
                    <Button variant="primary" onClick={onApply} disabledReason={restrictedReason} loading={applying}>
                        Apply all
                    </Button>
                    <Button size="icon" aria-label="Dismiss" tooltip="Dismiss" onClick={onDismiss}>
                        <IconX />
                    </Button>
                </ItemActions>
            </Item>
            <QuillPathCleaningPreviewDialog suggestionId={suggestion.id} restrictedReason={restrictedReason} />
        </>
    )
}
