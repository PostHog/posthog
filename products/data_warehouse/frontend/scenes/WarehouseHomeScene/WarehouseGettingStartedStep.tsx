import posthog from 'posthog-js'

import { IconCheckCircle } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { WarehouseStepState } from './warehouseHomeLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

interface StepAction {
    label: string
    to: string
    dataAttr: string
}

interface WarehouseGettingStartedStepProps {
    step: 'connect_source' | 'create_view' | 'connect_tool' | 'create_login'
    index: number
    state: WarehouseStepState
    title: string
    description: string
    actions: StepAction[]
}

export function WarehouseGettingStartedStep({
    step,
    index,
    state,
    title,
    description,
    actions,
}: WarehouseGettingStartedStepProps): JSX.Element {
    const done = state === 'done'
    return (
        <Item variant="outline">
            <ItemMedia variant="icon">
                {state === 'loading' ? (
                    <Skeleton className="size-4" />
                ) : done ? (
                    <IconCheckCircle />
                ) : (
                    <Text size="sm" weight="medium" render={<span />}>
                        {index}
                    </Text>
                )}
            </ItemMedia>
            <ItemContent>
                <ItemTitle>{title}</ItemTitle>
                <ItemDescription>{description}</ItemDescription>
            </ItemContent>
            <ItemActions className="flex-wrap">
                {actions.map((action) => (
                    <Button
                        key={action.dataAttr}
                        variant={done ? 'default' : 'primary'}
                        nativeButton={false}
                        render={<LinkPrimitive to={action.to} />}
                        data-attr={action.dataAttr}
                        onClick={() => {
                            posthog.capture('warehouse getting started clicked', { step, done })
                        }}
                    >
                        {action.label}
                    </Button>
                ))}
            </ItemActions>
        </Item>
    )
}
