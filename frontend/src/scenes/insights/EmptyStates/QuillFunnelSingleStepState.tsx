import { IconFunnels, IconPlusSmall } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillInsightEmptyStateIcon } from './QuillInsightEmptyStateIcon'

export function QuillFunnelSingleStepState({
    actionable,
    onAddStep,
}: {
    actionable: boolean
    onAddStep: () => void
}): JSX.Element {
    return (
        <Empty data-attr="insight-empty-state" className="border-none px-4 py-6">
            <EmptyHeader>
                <QuillInsightEmptyStateIcon icon={<IconFunnels />} />
                <EmptyTitle>Add a second step</EmptyTitle>
                <EmptyDescription>A funnel needs at least two steps before it can calculate.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center">
                {actionable && (
                    <Button variant="primary" onClick={onAddStep} data-attr="add-action-event-button-empty-state">
                        <IconPlusSmall />
                        Add funnel step
                    </Button>
                )}
                <Button
                    variant="link"
                    render={
                        <LinkPrimitive
                            to="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-empty-state"
                            target="_blank"
                            data-attr="funnels-single-step-help"
                        />
                    }
                >
                    Learn more about funnels
                </Button>
            </EmptyContent>
        </Empty>
    )
}
