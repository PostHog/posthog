import { useActions, useValues } from 'kea'

import {
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import {
    NewInsightCardSpec,
    QuestionSection,
    useQuestionSections,
} from 'products/product_analytics/frontend/insights/newInsightMenu/NewInsightMenu'

import { withBackLink } from './analyticsBackLink'
import { newAnalyticsLogic } from './newAnalyticsLogic'

/** The insight type picker in a dialog, so the Analytics pages stay put until a type is chosen. */
export function NewInsightDialog(): JSX.Element {
    const { newInsightDialogOpen } = useValues(newAnalyticsLogic)
    const { setNewInsightDialogOpen } = useActions(newAnalyticsLogic)
    const sections = useQuestionSections()

    return (
        <Dialog open={newInsightDialogOpen} onOpenChange={(open: boolean) => !open && setNewInsightDialogOpen(false)}>
            <DialogContent size="wide" data-attr="analytics-new-insight-dialog">
                <DialogHeader>
                    <DialogTitle>New insight</DialogTitle>
                    <DialogDescription>Start from the question you want answered.</DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-5">
                    {sections.map((section) => (
                        <InsightSection key={section.title} section={section} />
                    ))}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

function InsightSection({ section }: { section: QuestionSection }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col">
                <ItemTitle>{section.title}</ItemTitle>
                <ItemDescription>{section.description}</ItemDescription>
            </div>
            <ItemGroup className="grid grid-cols-2 gap-2 @3xl:grid-cols-4">
                {section.cards.map((spec) => (
                    <InsightCard key={spec.key} spec={spec} />
                ))}
            </ItemGroup>
        </div>
    )
}

function InsightCard({ spec }: { spec: NewInsightCardSpec }): JSX.Element {
    const { setNewInsightDialogOpen } = useActions(newAnalyticsLogic)
    const Icon = spec.icon
    return (
        <Item
            variant="outline"
            size="sm"
            className="text-foreground hover:bg-fill-button-tertiary-hover hover:text-foreground"
            render={
                // The editor carries the way back to Analytics on to the saved insight.
                <LinkPrimitive
                    to={withBackLink(spec.to)}
                    data-attr={spec.dataAttr}
                    onClick={() => {
                        spec.onClick?.()
                        setNewInsightDialogOpen(false)
                    }}
                />
            }
        >
            <ItemMedia variant="icon" aria-hidden>
                <Icon className={spec.iconClassName} />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{spec.name}</ItemTitle>
                <ItemDescription className="line-clamp-2">{spec.description}</ItemDescription>
            </ItemContent>
        </Item>
    )
}
