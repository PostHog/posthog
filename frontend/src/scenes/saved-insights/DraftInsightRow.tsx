import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { SavedInsightListItem, savedInsightsLogic } from './savedInsightsLogic'

export function DraftInsightNameCell({ item }: { item: SavedInsightListItem }): JSX.Element {
    const summarizeInsight = useSummarizeInsight()
    return (
        <LemonTableLink
            to={urls.insightNew({ query: item.query ?? undefined })}
            title={
                <span className="flex items-center gap-2">
                    <i>{summarizeInsight(item.query) || 'Unsaved insight'}</i>
                    <LemonTag type="warning" size="small">
                        Draft
                    </LemonTag>
                </span>
            }
            description="Unsaved changes, only stored in this browser"
        />
    )
}

export function DraftInsightMoreMenu({ item }: { item: SavedInsightListItem }): JSX.Element {
    const { discardDraftQuery } = useActions(savedInsightsLogic)
    return (
        <More
            overlay={
                <>
                    <LemonButton
                        to={urls.insightNew({ query: item.query ?? undefined })}
                        data-attr="draft-insight-continue-editing"
                        fullWidth
                    >
                        Continue editing
                    </LemonButton>
                    <LemonDivider />
                    <LemonButton
                        status="danger"
                        onClick={discardDraftQuery}
                        data-attr="draft-insight-discard"
                        fullWidth
                    >
                        Discard draft
                    </LemonButton>
                </>
            }
        />
    )
}
