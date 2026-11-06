import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconFilter, IconPeople, IconPlus, IconSupport } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    IconStack,
    IconStackItem,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason, productHasEffectiveNoneAccess } from 'lib/utils/accessControlUtils'
import { retryImport } from 'lib/utils/retryImport'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

// The compose modal lives in the Support product. It loads on demand, so the shell does not import product code.
async function openComposeTicket(): Promise<void> {
    const { composeTicketLogic } = await retryImport(
        () => import('products/conversations/frontend/components/ComposeTicket/composeTicketLogic')
    )
    const logic = composeTicketLogic.findMounted() ?? composeTicketLogic
    if (!logic.isMounted()) {
        logic.mount()
    }
    logic.actions.openComposeModal()
}

interface NewPeopleItem {
    key: string
    title: string
    description: string
    icon: JSX.Element
    color: string
    onClick: () => void
    disabledReason?: string | null
}

function NewPeopleMenuItem({ item }: { item: NewPeopleItem }): JSX.Element {
    return (
        <DropdownMenuItem
            className="h-auto cursor-pointer items-start py-1.5 whitespace-normal"
            onClick={item.onClick}
            disabled={!!item.disabledReason}
            title={item.disabledReason ?? undefined}
            data-attr={`people-new-${item.key}`}
        >
            <IconStack className="mt-0.5 shrink-0">
                <IconStackItem color={item.color}>{item.icon}</IconStackItem>
            </IconStack>
            <ItemContent variant="menuItem">
                <ItemTitle>{item.title}</ItemTitle>
                <ItemDescription>{item.disabledReason ?? item.description}</ItemDescription>
            </ItemContent>
        </DropdownMenuItem>
    )
}

export function TodayNewPeopleButton(): JSX.Element {
    const customerAnalytics = useFeatureFlag('CUSTOMER_ANALYTICS')
    const journeys = useFeatureFlag('CUSTOMER_ANALYTICS_JOURNEYS')
    const { currentTeam } = useValues(teamLogic)

    const items: (NewPeopleItem | null)[] = [
        {
            key: 'cohort',
            title: 'Cohort',
            description: 'Save a group of people by their properties or behavior.',
            icon: <IconPeople />,
            color: 'var(--color-product-data-warehouse-light)',
            onClick: () => router.actions.push(urls.cohort('new')),
        },
        customerAnalytics && journeys
            ? {
                  key: 'journey',
                  title: 'Journey',
                  description: 'Map the steps customers take and see where they drop off.',
                  icon: <IconFilter />,
                  color: 'var(--color-product-customer-analytics-light)',
                  onClick: () => router.actions.push(urls.customerJourneyTemplates()),
                  disabledReason: getAccessControlDisabledReason(
                      AccessControlResourceType.CustomerAnalytics,
                      AccessControlLevel.Editor
                  ),
              }
            : null,
        // Like the Support row, the item is left out for people with no Ticket access.
        !productHasEffectiveNoneAccess(AccessControlResourceType.Ticket)
            ? {
                  key: 'ticket',
                  title: 'Ticket',
                  description: currentTeam?.conversations_enabled
                      ? 'Write to a customer, and keep the conversation in Support.'
                      : 'Turn on Support for this project to write to customers.',
                  icon: <IconSupport />,
                  color: 'var(--color-product-support-light)',
                  onClick: () =>
                      currentTeam?.conversations_enabled
                          ? void openComposeTicket()
                          : router.actions.push(urls.supportSettings()),
                  disabledReason: getAccessControlDisabledReason(
                      AccessControlResourceType.Ticket,
                      AccessControlLevel.Editor
                  ),
              }
            : null,
    ]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        className="-me-2 text-muted-foreground"
                        aria-label="New in People"
                        data-attr="today-new-people-header"
                    />
                }
            >
                <IconPlus />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-72">
                {items.map((item) => item && <NewPeopleMenuItem key={item.key} item={item} />)}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
