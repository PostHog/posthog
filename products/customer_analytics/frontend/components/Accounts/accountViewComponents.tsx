import posthog from 'posthog-js'

import { FEATURE_FLAGS, type FeatureFlagKey } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AccountPropertiesWidget } from '../../scenes/CustomerAnalyticsAccountScene/AccountPropertiesWidget'
import { getAccountWidgetProperties } from '../../scenes/CustomerAnalyticsAccountScene/accountPropertiesWidgetConfig'
import { AccountPropertiesWidgetConfiguration } from '../../scenes/CustomerAnalyticsAccountScene/AccountPropertiesWidgetConfiguration'
import { CustomerTasksTabContent } from '../CustomerTasks/CustomerTasksTabContent'
import { AccountAutomationsExpansion } from './AccountAutomationsExpansion'
import { AccountBillingExpansion } from './AccountBillingExpansion'
import { AccountConversationsExpansion } from './AccountConversationsExpansion'
import { AccountDotMatrixTile } from './AccountDotMatrixTile'
import { AccountFeatureRequestsExpansion } from './AccountFeatureRequestsExpansion'
import { AccountMeetingsExpansion } from './AccountMeetingsExpansion'
import { AccountNotesExpansion } from './AccountNotesExpansion'
import { AccountOpportunitiesExpansion } from './AccountOpportunitiesExpansion'
import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'
import { AccountRelationshipsExpansion } from './AccountRelationshipsExpansion'
import { AccountSessionReplays } from './AccountSessionReplays'
import { getAccountSqlQuery, getAccountSqlQueryConfigError } from './accountSqlQuery'
import { AccountSqlQueryTile } from './AccountSqlQueryTile'
import { AccountSqlQueryTileConfiguration } from './AccountSqlQueryTileConfiguration'
import { AccountUsersTable } from './AccountUsersTable'
import type {
    AccountViewTileConfig,
    AccountViewTileConfigEditorProps,
    AccountViewTileLogicProps,
    AccountViewWidgetProps,
} from './accountViewTileConfig'
import { AccountsEvents } from './constants'

export type AccountSystemTabKind =
    | 'notes'
    | 'tasks'
    | 'users'
    | 'relationships'
    | 'feature_requests'
    | 'usage'
    | 'spend'
    | 'opportunities'
    | 'conversations'
    | 'meetings'
    | 'automations'

export type AccountViewComponentKind =
    | AccountSystemTabKind
    | 'properties'
    | 'session_replays'
    | 'dot_matrix'
    | 'sql_query'
interface AccountViewComponentBase {
    tagName: string
    label: string
    featureFlag?: FeatureFlagKey
    Component: (props: AccountViewWidgetProps) => JSX.Element
    ConfigEditor?: (props: AccountViewTileConfigEditorProps) => JSX.Element
    getConfigError?: (config: AccountViewTileConfig) => string | undefined
    onConfigSaved?: (config: AccountViewTileConfig) => void
    tileInsetClassName?: string
    tileContentClassName?: string
    remountOnConfigReload?: boolean
    configEditorWidth?: number
    canDuplicate?: boolean
}

export interface AccountSystemTabDefinition extends AccountViewComponentBase {
    kind: AccountSystemTabKind
    systemTabId: `system:${AccountSystemTabKind}`
}

export type AccountViewComponentDefinition =
    | AccountSystemTabDefinition
    | (AccountViewComponentBase & {
          kind: 'properties' | 'session_replays' | 'dot_matrix' | 'sql_query'
          systemTabId?: never
      })

function getTileLogicProps({
    instanceId,
    initialConfig,
    onConfigChange,
}: AccountViewWidgetProps): AccountViewTileLogicProps {
    return { instanceId, initialConfig, onConfigChange }
}

function AccountUsersWidget(props: AccountViewWidgetProps): JSX.Element {
    const isUsersTableEnabled = useFeatureFlag('CUSTOMER_ANALYTICS_ACCOUNT_USERS_TABLE')
    return isUsersTableEnabled ? (
        <AccountUsersTable
            accountId={props.accountId}
            externalId={props.externalId}
            embedded={props.embedded}
            {...getTileLogicProps(props)}
        />
    ) : (
        <AccountRelatedUsersExpansion
            externalId={props.externalId}
            embedded={props.embedded}
            {...getTileLogicProps(props)}
        />
    )
}

export const ACCOUNT_VIEW_COMPONENTS: AccountViewComponentDefinition[] = [
    {
        kind: 'properties',
        tagName: 'Properties',
        label: 'Properties',
        Component: (props) => (
            <AccountPropertiesWidget
                accountId={props.accountId}
                projectId={props.projectId}
                {...getTileLogicProps(props)}
            />
        ),
        ConfigEditor: AccountPropertiesWidgetConfiguration,
        onConfigSaved: (config) =>
            posthog.capture(AccountsEvents.PropertiesWidgetConfigured, {
                property_count: getAccountWidgetProperties(config).length,
            }),
        // Match the sidebar's property inset.
        tileInsetClassName: 'px-4',
    },
    {
        kind: 'session_replays',
        tagName: 'SessionReplays',
        label: 'Session replays',
        Component: (props) => (
            <AccountSessionReplays
                accountId={props.accountId}
                externalId={props.externalId}
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'dot_matrix',
        tagName: 'DotMatrix',
        label: 'Dot matrix',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_DOT_MATRIX,
        Component: (props) => (
            <AccountDotMatrixTile
                accountId={props.accountId}
                externalId={props.externalId}
                {...getTileLogicProps(props)}
            />
        ),
        tileContentClassName: '',
        remountOnConfigReload: false,
    },
    {
        kind: 'sql_query',
        canDuplicate: true,
        tileContentClassName: 'min-w-0 p-0',
        tagName: 'SqlQuery',
        label: 'SQL query',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SQL_QUERY_TILE,
        Component: (props) => (
            <AccountSqlQueryTile
                accountId={props.accountId}
                externalId={props.externalId}
                instanceId={props.instanceId}
                initialConfig={props.initialConfig}
                onLoadingChange={props.onLoadingChange}
            />
        ),
        ConfigEditor: AccountSqlQueryTileConfiguration,
        configEditorWidth: 1000,
        getConfigError: getAccountSqlQueryConfigError,
        onConfigSaved: (config) =>
            posthog.capture(AccountsEvents.SqlQueryTileConfigured, {
                query_length: getAccountSqlQuery(config).length,
            }),
    },
    {
        kind: 'notes',
        tagName: 'Notes',
        label: 'Notes',
        systemTabId: 'system:notes',
        Component: (props) => (
            <AccountNotesExpansion
                accountId={props.accountId}
                embedded={props.embedded}
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'automations',
        tagName: 'Automations',
        label: 'Automations',
        systemTabId: 'system:automations',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_AUTOMATIONS_WIDGET,
        Component: (props) => (
            <AccountAutomationsExpansion
                accountId={props.accountId}
                instanceId={props.instanceId}
                embedded={props.embedded}
            />
        ),
    },
    {
        kind: 'tasks',
        tagName: 'Tasks',
        label: 'Tasks',
        systemTabId: 'system:tasks',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS,
        Component: (props) => (
            <CustomerTasksTabContent
                accountId={props.accountId}
                canCreate={userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Editor)}
                canViewAll={userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Viewer)}
                embedded={props.embedded}
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'users',
        tagName: 'Users',
        label: 'Users',
        systemTabId: 'system:users',
        Component: AccountUsersWidget,
    },
    {
        kind: 'relationships',
        tagName: 'Relationships',
        label: 'Relationships',
        systemTabId: 'system:relationships',
        Component: (props) => (
            <AccountRelationshipsExpansion
                accountId={props.accountId}
                embedded={props.embedded}
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'feature_requests',
        tagName: 'FeatureRequests',
        label: 'Feature requests',
        systemTabId: 'system:feature_requests',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS,
        Component: (props) => (
            <AccountFeatureRequestsExpansion
                accountId={props.accountId}
                embedded={props.embedded}
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'usage',
        tagName: 'Usage',
        label: 'Usage',
        systemTabId: 'system:usage',
        Component: (props) => (
            <AccountBillingExpansion
                accountId={props.accountId}
                externalId={props.externalId}
                kind="usage"
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'spend',
        tagName: 'Spend',
        label: 'Spend',
        systemTabId: 'system:spend',
        Component: (props) => (
            <AccountBillingExpansion
                accountId={props.accountId}
                externalId={props.externalId}
                kind="spend"
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'opportunities',
        tagName: 'Opportunities',
        label: 'Opportunities',
        systemTabId: 'system:opportunities',
        Component: (props) => (
            <AccountOpportunitiesExpansion
                accountId={props.accountId}
                instanceId={props.instanceId}
                embedded={props.embedded}
            />
        ),
    },
    {
        kind: 'conversations',
        tagName: 'Conversations',
        label: 'Conversations',
        systemTabId: 'system:conversations',
        Component: (props) => (
            <AccountConversationsExpansion
                accountId={props.accountId}
                embedded={props.embedded}
                {...getTileLogicProps(props)}
            />
        ),
    },
    {
        kind: 'meetings',
        tagName: 'Meetings',
        label: 'Meetings',
        systemTabId: 'system:meetings',
        featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
        Component: (props) => (
            <AccountMeetingsExpansion
                accountId={props.accountId}
                embedded={props.embedded}
                {...getTileLogicProps(props)}
            />
        ),
    },
]

export function listAvailableAccountViewComponents(featureFlags: FeatureFlagsSet): AccountViewComponentDefinition[] {
    return ACCOUNT_VIEW_COMPONENTS.filter(
        (component) => !component.featureFlag || !!featureFlags[component.featureFlag]
    )
}

export function listAvailableAccountSystemTabs(featureFlags: FeatureFlagsSet): AccountSystemTabDefinition[] {
    return listAvailableAccountViewComponents(featureFlags).filter(
        (component): component is AccountSystemTabDefinition => component.systemTabId !== undefined
    )
}

export function getAccountViewComponentByKind(
    kind: AccountViewComponentKind
): AccountViewComponentDefinition | undefined {
    return ACCOUNT_VIEW_COMPONENTS.find((component) => component.kind === kind)
}

export function getAccountViewComponentByTag(tagName: string): AccountViewComponentDefinition | undefined {
    return ACCOUNT_VIEW_COMPONENTS.find((component) => component.tagName === tagName)
}

export function getAccountViewComponentBySystemTabId(tabId: string): AccountViewComponentDefinition | undefined {
    return ACCOUNT_VIEW_COMPONENTS.find((component) => component.systemTabId === tabId)
}
