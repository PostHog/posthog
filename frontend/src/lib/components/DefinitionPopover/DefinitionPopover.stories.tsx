import type { Meta, StoryObj } from '@storybook/react'
import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { useRef } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import {
    AccessControlLevel,
    type ActionType,
    type EventDefinition,
    type PropertyDefinition,
    PropertyType,
    type UserBasicType,
} from '~/types'

import {
    defaultDataWarehousePopoverFields,
    eventTaxonomicGroupProps,
    propertyTaxonomicGroupProps,
    taxonomicFilterLogic,
} from '../TaxonomicFilter/taxonomicFilterLogic'
import { ControlledDefinitionPopover } from './DefinitionPopoverContents'
import { type DefinitionPopoverLogicProps, definitionPopoverLogic } from './definitionPopoverLogic'

const mockUser: UserBasicType = {
    id: 1,
    uuid: 'user-uuid-123',
    distinct_id: 'user-123',
    first_name: 'Alice',
    email: 'alice@posthog.com',
}

const mockEventImages = [
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2UwZjJmZSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMTwvdGV4dD48L3N2Zz4=',
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2ZlZTJlMiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMjwvdGV4dD48L3N2Zz4=',
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2UwZmVlOCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMzwvdGV4dD48L3N2Zz4=',
]

const mockEventDefinition: EventDefinition = {
    id: 'event-uuid-123',
    name: '$pageview',
    description: 'Triggered when a user views a page',
    tags: ['core', 'web'],
    verified: true,
    created_at: '2024-01-15T10:00:00Z',
    owner: mockUser,
    updated_at: '2024-04-20T14:30:00Z',
    updated_by: mockUser,
    last_seen_at: '2024-05-01T09:00:00Z',
    media_preview_urls: mockEventImages,
}

const mockPropertyDefinition: PropertyDefinition = {
    id: 'prop-uuid-456',
    name: '$current_url',
    description: 'The current URL of the page',
    tags: ['web'],
    is_numerical: false,
    property_type: PropertyType.String,
    verified: true,
    updated_at: '2024-04-25T16:00:00Z',
    updated_by: mockUser,
}

const mockActionDefinition: ActionType = {
    id: 1,
    name: 'User signed up',
    description: 'Tracks when a user completes the signup process',
    tags: ['conversion', 'critical'],
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            event: 'signup_completed',
            properties: [],
        },
    ],
    created_at: '2024-01-05T12:00:00Z',
    created_by: mockUser,
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2024-05-01T00:00:00Z',
    pinned_at: null,
    user_access_level: AccessControlLevel.Editor,
}

interface StoryWrapperProps {
    logicProps: DefinitionPopoverLogicProps
    item: EventDefinition | PropertyDefinition | ActionType
    groupType: TaxonomicFilterGroupType
}

const StoryWrapper: React.FC<StoryWrapperProps> = ({ logicProps, item, groupType }) => {
    const divRef = useRef<HTMLDivElement>(null)

    const group = {
        name: groupType,
        searchPlaceholder: '',
        type: groupType,
        getValue: (instance: any) => instance.name,
        ...(groupType === TaxonomicFilterGroupType.Events
            ? eventTaxonomicGroupProps
            : groupType === TaxonomicFilterGroupType.EventProperties
              ? propertyTaxonomicGroupProps()
              : {
                    getPopoverHeader: () => 'Action',
                    getIcon: undefined,
                }),
    }

    const taxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: 'definition-popover-story',
        taxonomicGroupTypes: [groupType],
    }

    return (
        <BindLogic logic={definitionPopoverLogic} props={logicProps}>
            <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
                <div className="p-4 bg-surface-primary" style={{ width: 400, height: 600 }}>
                    <div ref={divRef} className="p-2 border border-border rounded">
                        Hover target
                    </div>
                    <ControlledDefinitionPopover
                        visible={true}
                        item={item}
                        group={group}
                        highlightedItemElement={divRef.current}
                    />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

type Story = StoryObj<StoryWrapperProps>
const meta: Meta<StoryWrapperProps> = {
    title: 'Components/Definition popover',
    component: ControlledDefinitionPopover as any,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/event_definitions/:id': () => [200, mockEventDefinition],
                '/api/projects/:team_id/property_definitions/:id': () => [200, mockPropertyDefinition],
                '/api/projects/:team_id/actions/:id': () => [200, mockActionDefinition],
            },
        }),
    ],
    parameters: {
        mockDate: '2024-05-01 12:00:00',
    },
    render: (args) => <StoryWrapper {...args} />,
}
export default meta

export const Event: Story = {
    args: {
        logicProps: {
            type: TaxonomicFilterGroupType.Events,
        },
        item: mockEventDefinition,
        groupType: TaxonomicFilterGroupType.Events,
    },
}

export const Property: Story = {
    args: {
        logicProps: {
            type: TaxonomicFilterGroupType.EventProperties,
        },
        item: mockPropertyDefinition,
        groupType: TaxonomicFilterGroupType.EventProperties,
    },
}

export const Action: Story = {
    args: {
        logicProps: {
            type: TaxonomicFilterGroupType.Actions,
        },
        item: mockActionDefinition,
        groupType: TaxonomicFilterGroupType.Actions,
    },
}

export const WithoutDescription: Story = {
    args: {
        logicProps: {
            type: TaxonomicFilterGroupType.Events,
        },
        item: {
            ...mockEventDefinition,
            description: '',
        },
        groupType: TaxonomicFilterGroupType.Events,
    },
}

export const WithMarkdownDescription: Story = {
    render: () => {
        const logicProps: DefinitionPopoverLogicProps = {
            type: TaxonomicFilterGroupType.Events,
        }

        const definitionWithMarkdown: EventDefinition = {
            ...mockEventDefinition,
            description: `## Overview
This event tracks page views across the application.

**Key features:**
- Automatically captured on all pages
- Includes referrer information
- Contains page metadata

\`\`\`javascript
posthog.capture('$pageview', { url: window.location.href })
\`\`\``,
        }

        return (
            <StoryWrapper
                logicProps={logicProps}
                item={definitionWithMarkdown}
                groupType={TaxonomicFilterGroupType.Events}
            />
        )
    },
}

export const WithoutTimestamps: Story = {
    args: {
        logicProps: {
            type: TaxonomicFilterGroupType.Events,
        },
        item: {
            id: 'event-new',
            name: 'new_event',
            description: 'A newly created event with no timestamps',
            tags: [],
        } as EventDefinition,
        groupType: TaxonomicFilterGroupType.Events,
    },
}

// ---- Data warehouse column mapping (legacy / pill variant) --------------
// Covers the column-field pickers shown when a data warehouse table is
// selected as an insight series in the legacy TaxonomicFilter path
// (`DefinitionPopoverContents` → `DefinitionView` DWH branch). Pins the
// `pill` variant of the category-dropdown experiment. The rebuild variant
// of the same view is covered by `DataWarehouseConfig` in
// `TaxonomicFilterMenu.stories.tsx`.

const mockDataWarehouseTable = {
    id: 'dwh-table-1',
    name: 'stripe.charges',
    type: 'data_warehouse',
    fields: {
        id: { name: 'id', type: 'string' },
        amount: { name: 'amount', type: 'integer' },
        currency: { name: 'currency', type: 'string' },
        customer_email: { name: 'customer_email', type: 'string' },
        customer_id: { name: 'customer_id', type: 'string' },
        description: { name: 'description', type: 'string' },
        created_at: { name: 'created_at', type: 'datetime' },
        updated_at: { name: 'updated_at', type: 'datetime' },
        refunded: { name: 'refunded', type: 'boolean' },
        distinct_id: { name: 'distinct_id', type: 'string' },
    },
}

const dataWarehouseGroup = {
    name: 'Data warehouse tables',
    searchPlaceholder: 'data warehouse tables',
    type: TaxonomicFilterGroupType.DataWarehouse,
    getValue: (instance: any) => instance.name,
    getName: (instance: any) => instance.name,
    getPopoverHeader: () => 'Data warehouse table',
}

const DataWarehouseColumnMappingWrapper = (): JSX.Element => {
    const divRef = useRef<HTMLDivElement>(null)
    return (
        <BindLogic logic={definitionPopoverLogic} props={{ type: TaxonomicFilterGroupType.DataWarehouse }}>
            <BindLogic
                logic={taxonomicFilterLogic}
                props={{
                    taxonomicFilterLogicKey: 'definition-popover-dwh-story',
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.DataWarehouse],
                    dataWarehousePopoverFields: defaultDataWarehousePopoverFields,
                }}
            >
                <div className="p-4 bg-surface-primary" style={{ width: 500, height: 600 }}>
                    <div ref={divRef} className="p-2 border border-border rounded">
                        Hover target
                    </div>
                    <ControlledDefinitionPopover
                        visible={true}
                        item={mockDataWarehouseTable as any}
                        group={dataWarehouseGroup as any}
                        highlightedItemElement={divRef.current}
                    />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const DataWarehouseColumnMapping: Story = {
    render: () => <DataWarehouseColumnMappingWrapper />,
    parameters: {
        featureFlags: { [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: 'pill' },
        testOptions: { waitForSelector: '.definition-popover-data-warehouse-schema-form' },
    },
    // Open the first column picker so the snapshot captures the filterable
    // search-input dropdown, not just the closed control. The popover renders
    // into a portal (document.body), outside canvasElement, so query via
    // `screen` rather than `within(canvasElement)`.
    play: async () => {
        const [firstColumnSelect] = await screen.findAllByRole('textbox')
        await userEvent.click(firstColumnSelect)
        // Wait for an option row so the snapshot is taken with the dropdown open.
        await screen.findByRole('button', { name: /distinct_id \(string\)/ })
    },
}
