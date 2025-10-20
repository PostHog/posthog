import { EventSourceMessage, fetchEventSource } from '@microsoft/fetch-event-source'
import { encodeParams } from 'kea-router'
import posthog from 'posthog-js'

import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { humanFriendlyDuration, objectClean, toParams } from 'lib/utils'
import { CohortCalculationHistoryResponse } from 'scenes/cohorts/cohortCalculationHistorySceneLogic'
import { MaxBillingContext } from 'scenes/max/maxBillingContextLogic'
import { NotebookListItemType, NotebookNodeResource, NotebookType } from 'scenes/notebooks/types'
import { RecordingComment } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { LINK_PAGE_SIZE, SURVEY_PAGE_SIZE } from 'scenes/surveys/constants'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'
import {
    DashboardFilter,
    DataWarehouseManagedViewsetKind,
    DatabaseSerializedFieldType,
    EndpointLastExecutionTimesRequest,
    EndpointRequest,
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingRelationalIssue,
    ExternalDataSourceType,
    FileSystemCount,
    FileSystemEntry,
    HogCompileResponse,
    HogQLQuery,
    HogQLQueryResponse,
    HogQLVariable,
    LogMessage,
    LogsQuery,
    Node,
    NodeKind,
    PersistedFolder,
    QuerySchema,
    QueryStatusResponse,
    RecordingsQuery,
    RecordingsQueryResponse,
    RefreshType,
    SourceConfig,
    TileFilters,
} from '~/queries/schema/schema-general'
import { HogQLQueryString, setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ActionType,
    ActivityScope,
    AppMetricsTotalsV2Response,
    AppMetricsV2RequestParams,
    AppMetricsV2Response,
    BatchExportBackfill,
    BatchExportConfiguration,
    BatchExportConfigurationTest,
    BatchExportConfigurationTestStep,
    BatchExportRun,
    BatchExportService,
    CohortType,
    CommentCreationParams,
    CommentType,
    ConversationDetail,
    CoreMemory,
    CreateGroupParams,
    CyclotronJobFiltersType,
    CyclotronJobTestInvocationResult,
    DashboardTemplateEditorType,
    DashboardTemplateListParams,
    DashboardTemplateType,
    DashboardType,
    DataColorThemeModel,
    DataModelingJob,
    DataWarehouseActivityRecord,
    DataWarehouseManagedViewsetSavedQuery,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDraft,
    DataWarehouseSourceRowCount,
    DataWarehouseTable,
    DataWarehouseViewLink,
    Dataset,
    DatasetItem,
    EarlyAccessFeatureType,
    EmailSenderDomainStatus,
    EndpointType,
    EventDefinition,
    EventDefinitionMetrics,
    EventDefinitionType,
    EventType,
    EventsListQueryParams,
    Experiment,
    ExportedAssetType,
    ExternalDataJob,
    ExternalDataSource,
    ExternalDataSourceCreatePayload,
    ExternalDataSourceRevenueAnalyticsConfig,
    ExternalDataSourceSchema,
    ExternalDataSourceSyncSchema,
    FeatureFlagStatusResponse,
    FeatureFlagType,
    GoogleAdsConversionActionType,
    Group,
    GroupListParams,
    HogFunctionIconResponse,
    HogFunctionStatus,
    HogFunctionTemplateType,
    HogFunctionType,
    HogFunctionTypeType,
    InsightModel,
    IntegrationType,
    LineageGraph,
    LinearTeamType,
    LinkType,
    LinkedInAdsAccountType,
    LinkedInAdsConversionRuleType,
    ListOrganizationMembersParams,
    LogEntry,
    LogEntryRequestParams,
    MediaUploadResponse,
    NewEarlyAccessFeatureType,
    type OAuthApplicationPublicMetadata,
    OrganizationFeatureFlags,
    OrganizationFeatureFlagsCopyBody,
    OrganizationMemberScopedApiKeysResponse,
    OrganizationMemberType,
    OrganizationType,
    PersonListParams,
    PersonType,
    PersonalAPIKeyType,
    PluginConfigTypeNew,
    PluginConfigWithPluginInfoNew,
    PluginLogEntry,
    ProjectType,
    PropertyDefinition,
    PropertyDefinitionType,
    QueryBasedInsightModel,
    QueryTabState,
    RawAnnotationType,
    RawBatchExportBackfill,
    RawBatchExportRun,
    RoleMemberType,
    RoleType,
    SavedSessionRecordingPlaylistsResult,
    ScheduledChangeType,
    SchemaIncrementalFieldsResponse,
    SearchListParams,
    SearchResponse,
    SessionRecordingPlaylistType,
    SessionRecordingSnapshotParams,
    SessionRecordingSnapshotResponse,
    SessionRecordingType,
    SessionRecordingUpdateType,
    SessionSummaryResponse,
    SharingConfigurationType,
    SlackChannelType,
    SubscriptionType,
    Survey,
    SurveyStatsResponse,
    TeamType,
    TwilioPhoneNumberType,
    UserBasicType,
    UserInterviewType,
    UserType,
} from '~/types'

import {
    ErrorTrackingRule,
    ErrorTrackingRuleType,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/rules/types'
import { Task, TaskUpsertProps } from 'products/tasks/frontend/types'
import { OptOutEntry } from 'products/workflows/frontend/OptOuts/optOutListLogic'
import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/messageTemplatesLogic'
import { HogflowTestResult } from 'products/workflows/frontend/Workflows/hogflows/steps/types'
import { HogFlow } from 'products/workflows/frontend/Workflows/hogflows/types'

import { MaxUIContext } from '../scenes/max/maxTypes'
import { AlertType, AlertTypeWrite } from './components/Alerts/types'
import {
    ErrorTrackingFingerprint,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameRecord,
    ErrorTrackingSymbolSet,
    SymbolSetStatusFilter,
} from './components/Errors/types'
import {
    ACTIVITY_PAGE_SIZE,
    COHORT_PERSONS_QUERY_LIMIT,
    EVENT_DEFINITIONS_PER_PAGE,
    EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
    LOGS_PORTION_LIMIT,
} from './constants'
import type { ProductIntentProperties } from './utils/product-intents'

/**
 * WARNING: Be very careful importing things here. This file is heavily used and can trigger a lot of cyclic imports
 * Preferably create a dedicated file in utils/..
 */

export type CheckboxValueType = string | number | boolean

const PAGINATION_DEFAULT_MAX_PAGES = 10

export interface PaginatedResponse<T> {
    results: T[]
    next?: string | null
    previous?: string | null
}

export interface CountedPaginatedResponse<T> extends PaginatedResponse<T> {
    count: number
}

export interface CountedPaginatedResponseWithUsers<T> extends CountedPaginatedResponse<T> {
    users: UserBasicType[]
}

export interface ActivityLogPaginatedResponse<T> extends PaginatedResponse<T> {
    count: number
}

export interface ApiMethodOptions {
    signal?: AbortSignal
    headers?: Record<string, any>
}

export class ApiError extends Error {
    /** Django REST Framework `detail` - used in downstream error handling. */
    detail: string | null
    /** Django REST Framework `code` - used in downstream error handling. */
    code: string | null
    /** Django REST Framework `statusText` - used in downstream error handling. */
    statusText: string | null
    /** Django REST Framework `attr` - used in downstream error handling. */
    attr: string | null

    /** Link to external resources, e.g. stripe invoices */
    link: string | null

    constructor(
        message?: string,
        public status?: number,
        public headers?: Headers,
        public data?: any
    ) {
        message = message || `API request failed with status: ${status ?? 'unknown'}`
        super(message)
        this.statusText = data?.statusText || null
        this.detail = data?.detail || null
        this.code = data?.code || null
        this.link = data?.link || null
        this.attr = data?.attr || null
    }

    /**
     * For when the API returned a 429 (Too Many Requests) error:
     * If the `Retry-After` header is present, return a human-friendly duration, e.g. "in 4 hours", otherwise just "later".
     * Return null for other status codes.
     */
    get formattedRetryAfter(): string | null {
        if (this.status !== 429) {
            return null
        }
        if (this.headers?.has('Retry-After')) {
            const retryAfter = this.headers.get('Retry-After') as string
            let secondsLeft = Number(retryAfter) // Let's assume we're dealing with an integer by default
            if (isNaN(secondsLeft)) {
                // Nope, here we're dealing with date in this format: Wed, 21 Oct 2015 07:28:00 GMT
                secondsLeft = dayjs(retryAfter).diff(dayjs(), 'seconds')
            }
            return `in ${humanFriendlyDuration(secondsLeft, { maxUnits: 2 })}`
        }
        return 'later'
    }
}

const CSRF_COOKIE_NAME = 'posthog_csrftoken'

export function getCookie(name: string): string | null {
    let cookieValue: string | null = null
    if (document.cookie && document.cookie !== '') {
        for (let cookie of document.cookie.split(';')) {
            cookie = cookie.trim()
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === name + '=') {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1))
                break
            }
        }
    }
    return cookieValue
}

export async function getJSONOrNull(response: Response): Promise<any> {
    try {
        return await response.json()
    } catch {
        return null
    }
}

export class ApiConfig {
    private static _currentOrganizationId: OrganizationType['id'] | null = null
    private static _currentProjectId: ProjectType['id'] | null = null
    private static _currentTeamId: TeamType['id'] | null = null

    static getCurrentOrganizationId(): OrganizationType['id'] {
        if (!this._currentOrganizationId) {
            throw new Error('Organization ID is not known.')
        }
        return this._currentOrganizationId
    }

    static setCurrentOrganizationId(id: OrganizationType['id'] | null): void {
        this._currentOrganizationId = id
    }

    static getCurrentTeamId(): TeamType['id'] {
        if (!this._currentTeamId) {
            throw new Error('Team ID is not known.')
        }
        return this._currentTeamId
    }

    static setCurrentTeamId(id: TeamType['id']): void {
        this._currentTeamId = id
    }

    static getCurrentProjectId(): ProjectType['id'] {
        if (!this._currentProjectId) {
            throw new Error('Project ID is not known.')
        }
        return this._currentProjectId
    }

    static setCurrentProjectId(id: ProjectType['id']): void {
        this._currentProjectId = id
    }
}

export class ApiRequest {
    private pathComponents: string[]
    private queryString: string | undefined

    public constructor() {
        this.pathComponents = []
    }

    // URL assembly

    public assembleEndpointUrl(): string {
        let url = this.pathComponents.join('/')
        if (this.queryString) {
            if (!this.queryString.startsWith('?')) {
                url += '?'
            }
            url += this.queryString
        }
        return url
    }

    public assembleFullUrl(includeLeadingSlash = false): string {
        return (includeLeadingSlash ? '/api/' : 'api/') + this.assembleEndpointUrl()
    }

    // Generic endpoint composition

    private addPathComponent(component: string | number): ApiRequest {
        this.pathComponents.push(component.toString())
        return this
    }

    private addEncodedPathComponent(component: string | number): ApiRequest {
        this.pathComponents.push(encodeURIComponent(component.toString()))
        return this
    }

    public withQueryString(queryString?: string | Record<string, any>): ApiRequest {
        this.queryString = typeof queryString === 'object' ? toParams(queryString) : queryString
        return this
    }

    public withAction(apiAction: string): ApiRequest {
        return this.addPathComponent(apiAction)
    }

    // API-aware endpoint composition

    // # Utils
    public current(): ApiRequest {
        return this.addPathComponent('@current')
    }

    // # Organizations
    public organizations(): ApiRequest {
        return this.addPathComponent('organizations')
    }

    public organizationsDetail(id: OrganizationType['id'] = ApiConfig.getCurrentOrganizationId()): ApiRequest {
        return this.organizations().addPathComponent(id)
    }

    public organizationFeatureFlags(orgId: OrganizationType['id'], featureFlagKey: FeatureFlagType['key']): ApiRequest {
        return this.organizations()
            .addPathComponent(orgId)
            .addPathComponent('feature_flags')
            .addEncodedPathComponent(featureFlagKey) // Never trust user input.
    }

    public copyOrganizationFeatureFlags(orgId: OrganizationType['id']): ApiRequest {
        return this.organizations()
            .addPathComponent(orgId)
            .addPathComponent('feature_flags')
            .addPathComponent('copy_flags')
    }

    // # Projects
    public projects(): ApiRequest {
        return this.addPathComponent('projects')
    }

    public projectsDetail(id: ProjectType['id'] = ApiConfig.getCurrentProjectId()): ApiRequest {
        return this.projects().addPathComponent(id)
    }

    // # Environments
    public environments(): ApiRequest {
        return this.addPathComponent('environments')
    }

    public environmentsDetail(id: TeamType['id'] = ApiConfig.getCurrentTeamId()): ApiRequest {
        return this.environments().addPathComponent(id)
    }

    // # CSP reporting

    public cspReportingExplanation(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('csp-reporting').addPathComponent('explain')
    }

    // # Insights
    public insights(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('insights')
    }

    public insight(id: QueryBasedInsightModel['id'], teamId?: TeamType['id']): ApiRequest {
        return this.insights(teamId).addPathComponent(id)
    }

    public insightsActivity(teamId?: TeamType['id']): ApiRequest {
        return this.insights(teamId).addPathComponent('activity')
    }

    public insightSharing(id: QueryBasedInsightModel['id'], teamId?: TeamType['id']): ApiRequest {
        return this.insight(id, teamId).addPathComponent('sharing')
    }

    public insightSharingPasswords(id: QueryBasedInsightModel['id'], teamId?: TeamType['id']): ApiRequest {
        return this.insightSharing(id, teamId).addPathComponent('passwords')
    }

    public insightSharingPassword(
        id: QueryBasedInsightModel['id'],
        passwordId: string,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.insightSharingPasswords(id, teamId).addPathComponent(passwordId)
    }

    public insightsCancel(teamId?: TeamType['id']): ApiRequest {
        return this.insights(teamId).addPathComponent('cancel')
    }

    // # File System
    public fileSystem(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('file_system')
    }

    public fileSystemUnfiled(type?: string, teamId?: TeamType['id']): ApiRequest {
        const path = this.fileSystem(teamId).addPathComponent('unfiled')
        if (type) {
            path.withQueryString({ type })
        }
        return path
    }

    public fileSystemDetail(id: NonNullable<FileSystemEntry['id']>, teamId?: TeamType['id']): ApiRequest {
        return this.fileSystem(teamId).addPathComponent(id)
    }

    public fileSystemMove(id: NonNullable<FileSystemEntry['id']>, teamId?: TeamType['id']): ApiRequest {
        return this.fileSystem(teamId).addPathComponent(id).addPathComponent('move')
    }

    public fileSystemLink(id: NonNullable<FileSystemEntry['id']>, teamId?: TeamType['id']): ApiRequest {
        return this.fileSystem(teamId).addPathComponent(id).addPathComponent('link')
    }

    public fileSystemCount(id: NonNullable<FileSystemEntry['id']>, teamId?: TeamType['id']): ApiRequest {
        return this.fileSystem(teamId).addPathComponent(id).addPathComponent('count')
    }

    public fileSystemShortcut(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('file_system_shortcut')
    }

    public fileSystemShortcutDetail(id: NonNullable<FileSystemEntry['id']>, teamId?: TeamType['id']): ApiRequest {
        return this.fileSystemShortcut(teamId).addPathComponent(id)
    }

    // # Persisted folder
    public persistedFolder(projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('persisted_folder')
    }
    public persistedFolderDetail(id: NonNullable<PersistedFolder['id']>, projectId?: ProjectType['id']): ApiRequest {
        return this.persistedFolder(projectId).addPathComponent(id)
    }

    // # Plugins
    public plugins(orgId?: OrganizationType['id']): ApiRequest {
        return this.organizationsDetail(orgId).addPathComponent('plugins')
    }

    public pluginsActivity(orgId?: OrganizationType['id']): ApiRequest {
        return this.plugins(orgId).addPathComponent('activity')
    }

    public pluginConfigs(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('plugin_configs')
    }

    public pluginConfig(id: number, teamId?: TeamType['id']): ApiRequest {
        return this.pluginConfigs(teamId).addPathComponent(id)
    }

    public hog(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('hog')
    }

    public hogFunctions(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('hog_functions')
    }

    public hogFunction(id: HogFunctionType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.hogFunctions(teamId).addPathComponent(id)
    }

    public hogFunctionTemplates(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('hog_function_templates')
    }

    public hogFunctionTemplate(id: HogFunctionTemplateType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.hogFunctionTemplates(teamId).addPathComponent(id)
    }

    // # Links
    public links(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('links')
    }

    public link(id: LinkType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.links(teamId).addPathComponent(id)
    }

    // # Actions
    public actions(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('actions')
    }

    public actionsDetail(actionId: ActionType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.actions(teamId).addPathComponent(actionId)
    }

    // # Comments
    public comments(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('comments')
    }

    public comment(id: CommentType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.comments(teamId).addPathComponent(id)
    }

    // # Exports
    public exports(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('exports')
    }

    public export(id: number, teamId?: TeamType['id']): ApiRequest {
        return this.exports(teamId).addPathComponent(id)
    }

    // # Events
    public events(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('events')
    }

    public event(id: EventType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.events(teamId).addPathComponent(id)
    }

    public tags(projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('tags')
    }

    // # Logs
    public logs(projectId?: ProjectType['id']): ApiRequest {
        return this.environmentsDetail(projectId).addPathComponent('logs')
    }

    public logsQuery(projectId?: ProjectType['id']): ApiRequest {
        return this.logs(projectId).addPathComponent('query')
    }

    public logsSparkline(projectId?: ProjectType['id']): ApiRequest {
        return this.logs(projectId).addPathComponent('sparkline')
    }

    // # Data management
    public eventDefinitions(projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('event_definitions')
    }

    public eventDefinitionDetail(eventDefinitionId: EventDefinition['id'], projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('event_definitions').addPathComponent(eventDefinitionId)
    }

    public propertyDefinitions(projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('property_definitions')
    }

    public propertyDefinitionDetail(
        propertyDefinitionId: PropertyDefinition['id'],
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.projectsDetail(teamId)
            .addPathComponent('property_definitions')
            .addPathComponent(propertyDefinitionId)
    }

    public propertyDefinitionSeenTogether(
        eventNames: string[],
        propertyDefinitionName: PropertyDefinition['name'],
        teamId?: TeamType['id']
    ): ApiRequest {
        const queryParams = toParams({ event_names: eventNames, property_name: propertyDefinitionName }, true)

        return this.projectsDetail(teamId)
            .addPathComponent('property_definitions')
            .addPathComponent('seen_together')
            .withQueryString(queryParams)
    }

    public sessionPropertyDefinitions(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('sessions').addPathComponent('property_definitions')
    }

    public dataManagementActivity(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('data_management').addPathComponent('activity')
    }

    // # Cohorts
    public cohorts(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('cohorts')
    }

    public cohortsDetail(cohortId: CohortType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.cohorts(teamId).addPathComponent(cohortId)
    }

    public cohortsDetailPersons(cohortId: CohortType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.cohorts(teamId).addPathComponent(cohortId).addPathComponent('persons')
    }

    public cohortsAddPersonsToStatic(cohortId: CohortType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.cohorts(teamId).addPathComponent(cohortId).addPathComponent('add_persons_to_static_cohort')
    }

    public cohortsRemovePersonFromStatic(cohortId: CohortType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.cohorts(teamId).addPathComponent(cohortId).addPathComponent('remove_person_from_static_cohort')
    }

    public cohortsDuplicate(cohortId: CohortType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.cohortsDetail(cohortId, teamId).addPathComponent('duplicate_as_static_cohort')
    }

    public cohortsCalculationHistory(cohortId: CohortType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.cohortsDetail(cohortId, teamId).addPathComponent('calculation_history')
    }

    // Recordings
    public recordings(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('session_recordings')
    }

    public recording(recordingId: SessionRecordingType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.recordings(teamId).addPathComponent(recordingId)
    }

    public recordingMatchingEvents(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId)
            .addPathComponent('session_recordings')
            .addPathComponent('matching_events')
    }

    public recordingPlaylists(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('session_recording_playlists')
    }

    public recordingPlaylist(
        playlistId?: SessionRecordingPlaylistType['short_id'],
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.projectsDetail(teamId)
            .addPathComponent('session_recording_playlists')
            .addPathComponent(String(playlistId))
    }

    public recordingSharing(id: SessionRecordingType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.recording(id, teamId).addPathComponent('sharing')
    }

    public recordingSharingPasswords(id: SessionRecordingType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.recordingSharing(id, teamId).addPathComponent('passwords')
    }

    public recordingSharingPassword(
        id: SessionRecordingType['id'],
        passwordId: string,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.recordingSharingPasswords(id, teamId).addPathComponent(passwordId)
    }

    // # Dashboards
    public dashboards(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('dashboards')
    }

    public dashboardsDetail(dashboardId: DashboardType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dashboards(teamId).addPathComponent(dashboardId)
    }

    public dashboardCollaborators(
        dashboardId: DashboardType['id'],
        projectId: ProjectType['id'] = ApiConfig.getCurrentProjectId() // Collaborators endpoint is project-level, not team-level
    ): ApiRequest {
        return this.dashboardsDetail(dashboardId, projectId).addPathComponent('collaborators')
    }

    public dashboardSharing(dashboardId: DashboardType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dashboardsDetail(dashboardId, teamId).addPathComponent('sharing')
    }

    public dashboardSharingPasswords(dashboardId: DashboardType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dashboardSharing(dashboardId, teamId).addPathComponent('passwords')
    }

    public dashboardSharingPassword(
        dashboardId: DashboardType['id'],
        passwordId: string,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.dashboardSharingPasswords(dashboardId, teamId).addPathComponent(passwordId)
    }

    public dashboardCollaboratorsDetail(
        dashboardId: DashboardType['id'],
        userUuid: UserType['uuid'],
        projectId?: ProjectType['id']
    ): ApiRequest {
        return this.dashboardCollaborators(dashboardId, projectId).addPathComponent(userUuid)
    }

    // # Dashboard templates
    public dashboardTemplates(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('dashboard_templates')
    }

    public dashboardTemplatesDetail(
        dashboardTemplateId: DashboardTemplateType['id'],
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.dashboardTemplates(teamId).addPathComponent(dashboardTemplateId)
    }

    public dashboardTemplateSchema(): ApiRequest {
        return this.dashboardTemplates().addPathComponent('json_schema')
    }

    // # Experiments
    public experiments(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('experiments')
    }

    public experimentsDetail(experimentId: Experiment['id'], teamId?: TeamType['id']): ApiRequest {
        return this.experiments(teamId).addPathComponent(experimentId)
    }

    public experimentCreateExposureCohort(experimentId: Experiment['id'], teamId?: TeamType['id']): ApiRequest {
        return this.experimentsDetail(experimentId, teamId).addPathComponent('create_exposure_cohort_for_experiment')
    }

    // # Roles
    public roles(): ApiRequest {
        return this.organizations().current().addPathComponent('roles')
    }

    public rolesDetail(roleId: RoleType['id']): ApiRequest {
        return this.roles().addPathComponent(roleId)
    }

    public roleMemberships(roleId: RoleType['id']): ApiRequest {
        return this.rolesDetail(roleId).addPathComponent('role_memberships')
    }

    public roleMembershipsDetail(roleId: RoleType['id'], userUuid: UserType['uuid']): ApiRequest {
        return this.roleMemberships(roleId).addPathComponent(userUuid)
    }

    // # OrganizationMembers
    public organizationMembers(): ApiRequest {
        return this.organizations().current().addPathComponent('members')
    }

    public organizationMember(uuid: OrganizationMemberType['user']['uuid']): ApiRequest {
        return this.organizationMembers().addPathComponent(uuid)
    }

    public organizationMemberScopedApiKeys(uuid: OrganizationMemberType['user']['uuid']): ApiRequest {
        return this.organizationMember(uuid).addPathComponent('scoped_api_keys')
    }

    // # Persons
    public persons(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('persons')
    }

    public person(id: string | number, teamId?: TeamType['id']): ApiRequest {
        return this.persons(teamId).addPathComponent(id)
    }

    public personActivity(id: string | number | undefined): ApiRequest {
        if (id) {
            return this.person(id).addPathComponent('activity')
        }
        return this.persons().addPathComponent('activity')
    }

    // # Groups
    public groups(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('groups')
    }

    public group(index: number, key: string, teamId?: TeamType['id']): ApiRequest {
        return this.groups(teamId).withQueryString({
            group_type_index: index,
            group_key: key,
        })
    }

    public groupActivity(teamId?: TeamType['id']): ApiRequest {
        return this.groups(teamId).addPathComponent('activity')
    }

    // # Search
    public search(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('search')
    }

    // # Annotations
    public annotations(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('annotations')
    }

    public annotation(id: RawAnnotationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.annotations(teamId).addPathComponent(id)
    }

    // # Feature flags
    public featureFlags(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('feature_flags')
    }

    public featureFlag(id: FeatureFlagType['id'], teamId?: TeamType['id']): ApiRequest {
        if (!id) {
            throw new Error('Must provide an ID for the feature flag to construct the URL')
        }
        return this.featureFlags(teamId).addPathComponent(id)
    }

    public featureFlagCreateStaticCohort(id: FeatureFlagType['id'], teamId?: TeamType['id']): ApiRequest {
        if (!id) {
            throw new Error('Must provide an ID for the feature flag to construct the URL')
        }
        return this.featureFlag(id, teamId).addPathComponent('create_static_cohort_for_flag')
    }

    public featureFlagsActivity(id: FeatureFlagType['id'], teamId: TeamType['id']): ApiRequest {
        if (id) {
            return this.featureFlag(id, teamId).addPathComponent('activity')
        }
        return this.featureFlags(teamId).addPathComponent('activity')
    }

    public featureFlagScheduledChanges(teamId: TeamType['id'], featureFlagId: FeatureFlagType['id']): ApiRequest {
        return this.projectsDetail(teamId)
            .addPathComponent('scheduled_changes')
            .withQueryString(
                toParams({
                    model_name: 'FeatureFlag',
                    record_id: featureFlagId,
                })
            )
    }

    public featureFlagStatus(teamId: TeamType['id'], featureFlagId: FeatureFlagType['id']): ApiRequest {
        return this.projectsDetail(teamId)
            .addPathComponent('feature_flags')
            .addPathComponent(String(featureFlagId))
            .addPathComponent('status')
    }

    public featureFlagCreateScheduledChange(teamId: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('scheduled_changes')
    }

    public featureFlagDeleteScheduledChange(
        teamId: TeamType['id'],
        scheduledChangeId: ScheduledChangeType['id']
    ): ApiRequest {
        return this.projectsDetail(teamId)
            .addPathComponent('scheduled_changes')
            .addPathComponent(`${scheduledChangeId}`)
    }

    // # Features
    public earlyAccessFeatures(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('early_access_feature')
    }

    public earlyAccessFeature(id: EarlyAccessFeatureType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.earlyAccessFeatures(teamId).addPathComponent(id)
    }

    // # User interviews
    public userInterviews(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('user_interviews')
    }

    public userInterview(id: UserInterviewType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.userInterviews(teamId).addPathComponent(id)
    }

    // # Users
    public users(email?: string): ApiRequest {
        if (email) {
            return this.addPathComponent('users').withQueryString({ email })
        }
        return this.addPathComponent('users')
    }

    // # Tasks
    public tasks(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('tasks')
    }

    public task(id: Task['id'], teamId?: TeamType['id']): ApiRequest {
        return this.tasks(teamId).addPathComponent(id)
    }

    // # Surveys
    public surveys(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('surveys')
    }

    public surveysResponsesCount(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('surveys/responses_count')
    }

    public survey(id: Survey['id'], teamId?: TeamType['id']): ApiRequest {
        return this.surveys(teamId).addPathComponent(id)
    }

    public surveyActivity(id: Survey['id'] | undefined, teamId?: TeamType['id']): ApiRequest {
        if (id) {
            return this.survey(id, teamId).addPathComponent('activity')
        }
        return this.surveys(teamId).addPathComponent('activity')
    }

    // Error tracking
    public errorTracking(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('error_tracking')
    }

    public errorTrackingIssues(teamId?: TeamType['id']): ApiRequest {
        return this.errorTracking(teamId).addPathComponent('issues')
    }

    public errorTrackingIssue(id: ErrorTrackingIssue['id'], teamId?: TeamType['id']): ApiRequest {
        return this.errorTrackingIssues(teamId).addPathComponent(id)
    }

    public errorTrackingIssueMerge(into: ErrorTrackingIssue['id']): ApiRequest {
        return this.errorTrackingIssue(into).addPathComponent('merge')
    }

    public errorTrackingIssueSplit(into: ErrorTrackingIssue['id']): ApiRequest {
        return this.errorTrackingIssue(into).addPathComponent('split')
    }

    public errorTrackingIssueBulk(teamId?: TeamType['id']): ApiRequest {
        return this.errorTrackingIssues(teamId).addPathComponent('bulk')
    }

    public errorTrackingAssignIssue(into: ErrorTrackingIssue['id']): ApiRequest {
        return this.errorTrackingIssue(into).addPathComponent('assign')
    }

    public errorTrackingSimilarIssues(issueId: ErrorTrackingIssue['id'], teamId?: TeamType['id']): ApiRequest {
        return this.errorTrackingIssues(teamId).addPathComponent(`${issueId}/similar_issues`)
    }

    public errorTrackingExternalReference(teamId?: TeamType['id']): ApiRequest {
        return this.errorTracking(teamId).addPathComponent('external_references')
    }

    public errorTrackingIssueFingerprints(teamId?: TeamType['id']): ApiRequest {
        return this.errorTracking(teamId).addPathComponent('fingerprints')
    }

    public errorTrackingSymbolSets(teamId?: TeamType['id']): ApiRequest {
        return this.errorTracking(teamId).addPathComponent('symbol_sets')
    }

    public errorTrackingSymbolSet(id: ErrorTrackingSymbolSet['id']): ApiRequest {
        return this.errorTrackingSymbolSets().addPathComponent(id)
    }

    public errorTrackingStackFrames(): ApiRequest {
        return this.errorTracking().addPathComponent('stack_frames/batch_get')
    }

    public errorTrackingRules(ruleType: ErrorTrackingRuleType, teamId?: TeamType['id']): ApiRequest {
        return this.errorTracking(teamId).addPathComponent(ruleType)
    }

    public errorTrackingRule(ruleType: ErrorTrackingRuleType, id: ErrorTrackingRule['id']): ApiRequest {
        return this.errorTrackingRules(ruleType).addPathComponent(id)
    }

    public errorTrackingReorderRules(rule: ErrorTrackingRuleType): ApiRequest {
        return this.errorTrackingRules(rule).addPathComponent('reorder')
    }

    // # Warehouse
    public dataWarehouseTables(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('warehouse_tables')
    }

    public dataWarehouseTable(id: DataWarehouseTable['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dataWarehouseTables(teamId).addPathComponent(id)
    }

    // # Warehouse view
    public dataWarehouseSavedQueries(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('warehouse_saved_queries')
    }

    public dataWarehouseSavedQuery(id: DataWarehouseSavedQuery['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dataWarehouseSavedQueries(teamId).addPathComponent(id)
    }

    public dataWarehouseSavedQueryDrafts(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('warehouse_saved_query_drafts')
    }

    public dataWarehouseSavedQueryDraft(id: DataWarehouseSavedQueryDraft['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dataWarehouseSavedQueryDrafts(teamId).addPathComponent(id)
    }

    public dataWarehouseSavedQueryActivity(id: DataWarehouseSavedQuery['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dataWarehouseSavedQuery(id, teamId).addPathComponent('activity')
    }

    // # Data Modeling Jobs (ie) materialized view runs
    public dataWarehouseDataModelingJobs(
        savedQueryId: DataWarehouseSavedQuery['id'],
        pageSize = 10,
        offset = 0,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.environmentsDetail(teamId)
            .addPathComponent('data_modeling_jobs')
            .withQueryString({ saved_query_id: savedQueryId, limit: pageSize, offset })
    }

    // # Warehouse view link
    public dataWarehouseViewLinks(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('warehouse_view_link')
    }

    public dataWarehouseViewLink(id: DataWarehouseViewLink['id'], teamId?: TeamType['id']): ApiRequest {
        return this.dataWarehouseViewLinks(teamId).addPathComponent(id)
    }

    // # Query Tab State
    public queryTabState(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('query_tab_state')
    }

    public queryTabStateDetail(id: QueryTabState['id'], teamId?: TeamType['id']): ApiRequest {
        return this.queryTabState(teamId).addPathComponent(id)
    }

    public queryTabStateUser(teamId?: TeamType['id']): ApiRequest {
        return this.queryTabState(teamId).addPathComponent('user')
    }

    // # Subscriptions
    public subscriptions(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('subscriptions')
    }

    public subscription(id: SubscriptionType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.subscriptions(teamId).addPathComponent(id)
    }

    // # Integrations
    public integrations(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('integrations')
    }

    public integration(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id)
    }

    public integrationSlackChannels(
        id: IntegrationType['id'],
        forceRefresh: boolean,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('channels')
            .withQueryString({ force_refresh: forceRefresh })
    }

    public integrationSlackChannelsById(
        id: IntegrationType['id'],
        channelId: string,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('channels')
            .withQueryString({ channel_id: channelId })
    }

    public integrationTwilioPhoneNumbers(
        id: IntegrationType['id'],
        forceRefresh: boolean,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('twilio_phone_numbers')
            .withQueryString({ force_refresh: forceRefresh })
    }

    public integrationLinearTeams(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id).addPathComponent('linear_teams')
    }

    public integrationGitHubRepositories(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id).addPathComponent('github_repos')
    }

    public integrationGoogleAdsAccounts(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id).addPathComponent('google_accessible_accounts')
    }

    public integrationGoogleAdsConversionActions(
        id: IntegrationType['id'],
        params: { customerId: string; parentId: string },
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('google_conversion_actions')
            .withQueryString(params)
    }

    public integrationLinkedInAdsAccounts(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id).addPathComponent('linkedin_ads_accounts')
    }

    public integrationLinkedInAdsConversionRules(
        id: IntegrationType['id'],
        accountId: string,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('linkedin_ads_conversion_rules')
            .withQueryString({ accountId })
    }

    public integrationClickUpSpaces(
        id: IntegrationType['id'],
        workspaceId: string,
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('clickup_spaces')
            .withQueryString({ workspaceId })
    }

    public integrationClickUpLists(id: IntegrationType['id'], spaceId: string, teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId)
            .addPathComponent(id)
            .addPathComponent('clickup_lists')
            .withQueryString({ spaceId })
    }

    public integrationClickUpWorkspaces(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id).addPathComponent('clickup_workspaces')
    }

    public integrationEmailVerify(id: IntegrationType['id'], teamId?: TeamType['id']): ApiRequest {
        return this.integrations(teamId).addPathComponent(id).addPathComponent('email/verify')
    }

    public media(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('uploaded_media')
    }

    // # Alerts
    public alerts(alertId?: AlertType['id'], insightId?: InsightModel['id'], teamId?: TeamType['id']): ApiRequest {
        if (alertId) {
            return this.environmentsDetail(teamId)
                .addPathComponent('alerts')
                .addPathComponent(alertId)
                .withQueryString({
                    insight_id: insightId,
                })
        }

        return this.environmentsDetail(teamId).addPathComponent('alerts').withQueryString({
            insight_id: insightId,
        })
    }

    public alert(alertId: AlertType['id']): ApiRequest {
        return this.alerts(alertId)
    }

    // Resource Access Permissions

    public featureFlagAccessPermissions(flagId: FeatureFlagType['id']): ApiRequest {
        return this.featureFlag(flagId).addPathComponent('role_access')
    }

    // Queries
    public query(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('query')
    }

    public queryStatus(queryId: string, showProgress: boolean, teamId?: TeamType['id']): ApiRequest {
        const apiRequest = this.query(teamId).addPathComponent(queryId)
        if (showProgress) {
            return apiRequest.withQueryString('show_progress=true')
        }
        return apiRequest
    }

    public queryUpgrade(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('query').addPathComponent('upgrade')
    }

    public queryLog(queryId: string, teamId?: TeamType['id']): ApiRequest {
        return this.query(teamId).addPathComponent(queryId).addPathComponent('log')
    }

    // Endpoints
    public endpoint(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('endpoints')
    }

    public endpointDetail(name: string): ApiRequest {
        return this.endpoint().addPathComponent(name)
    }

    public lastExecutionTimes(): ApiRequest {
        return this.addPathComponent('last_execution_times')
    }

    // Managed Viewsets
    public dataWarehouseManagedViewset(kind: DataWarehouseManagedViewsetKind, teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('managed_viewsets').addPathComponent(kind)
    }

    // Conversations
    public conversations(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('conversations')
    }

    public conversation(id: string, teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('conversations').addPathComponent(id)
    }

    // Notebooks
    public notebooks(projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('notebooks')
    }

    public notebook(id: NotebookType['short_id'], teamId?: TeamType['id']): ApiRequest {
        return this.notebooks(teamId).addPathComponent(id)
    }

    // Batch Exports
    public batchExports(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('batch_exports')
    }

    public batchExport(id: BatchExportConfiguration['id'], teamId?: TeamType['id']): ApiRequest {
        return this.batchExports(teamId).addPathComponent(id)
    }

    public batchExportRuns(id: BatchExportConfiguration['id'], teamId?: TeamType['id']): ApiRequest {
        return this.batchExports(teamId).addPathComponent(id).addPathComponent('runs')
    }

    public batchExportBackfills(id: BatchExportConfiguration['id'], teamId?: TeamType['id']): ApiRequest {
        return this.batchExports(teamId).addPathComponent(id).addPathComponent('backfills')
    }

    public batchExportRun(
        id: BatchExportConfiguration['id'],
        runId: BatchExportRun['id'],
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.batchExportRuns(id, teamId).addPathComponent(runId)
    }

    public batchExportBackfill(
        id: BatchExportConfiguration['id'],
        backfillId: BatchExportBackfill['id'],
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.batchExportBackfills(id, teamId).addPathComponent(backfillId)
    }

    // External Data Source
    public externalDataSources(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('external_data_sources')
    }

    public externalDataSource(sourceId: ExternalDataSource['id'], teamId?: TeamType['id']): ApiRequest {
        return this.externalDataSources(teamId).addPathComponent(sourceId)
    }

    public dataWarehouse(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('data_warehouse')
    }

    public externalDataSchemas(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('external_data_schemas')
    }

    public externalDataSourceSchema(schemaId: ExternalDataSourceSchema['id'], teamId?: TeamType['id']): ApiRequest {
        return this.externalDataSchemas(teamId).addPathComponent(schemaId)
    }

    public externalDataSourceRevenueAnalyticsConfig(
        sourceId: ExternalDataSource['id'],
        teamId?: TeamType['id']
    ): ApiRequest {
        return this.externalDataSources(teamId).addPathComponent(sourceId).addPathComponent('revenue_analytics_config')
    }

    // Fix HogQL errors
    public fixHogQLErrors(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('fix_hogql')
    }

    // Insight Variables
    public insightVariables(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('insight_variables')
    }

    public insightVariable(variableId: string, teamId?: TeamType['id']): ApiRequest {
        return this.insightVariables(teamId).addPathComponent(variableId)
    }

    public upstream(modelId: string, teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId)
            .addPathComponent('lineage')
            .addPathComponent('get_upstream')
            .withQueryString({
                model_id: modelId,
            })
    }

    // ActivityLog
    public activityLog(projectId?: ProjectType['id']): ApiRequest {
        return this.projectsDetail(projectId).addPathComponent('activity_log')
    }

    // Personal API keys
    public personalApiKeys(): ApiRequest {
        return this.addPathComponent('personal_api_keys')
    }

    public personalApiKey(id: PersonalAPIKeyType['id']): ApiRequest {
        return this.personalApiKeys().addPathComponent(id)
    }

    // Request finalization
    public async get(options?: ApiMethodOptions): Promise<any> {
        return await api.get(this.assembleFullUrl(), options)
    }

    public async getResponse(options?: ApiMethodOptions): Promise<Response> {
        return await api.getResponse(this.assembleFullUrl(), options)
    }

    public async update(options?: ApiMethodOptions & { data: any }): Promise<any> {
        return await api.update(this.assembleFullUrl(), options?.data, options)
    }

    public async put(options?: ApiMethodOptions & { data: any }): Promise<any> {
        return await api.put(this.assembleFullUrl(), options?.data, options)
    }

    public async create(options?: ApiMethodOptions & { data: any }): Promise<any> {
        return await api.create(this.assembleFullUrl(), options?.data, options)
    }

    public async delete(): Promise<any> {
        return await api.delete(this.assembleFullUrl())
    }

    // Data color themes
    public dataColorThemes(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('data_color_themes')
    }

    public dataColorTheme(id: DataColorThemeModel['id'], teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('data_color_themes').addPathComponent(id)
    }

    public addProductIntent(): ApiRequest {
        return this.environments().current().addPathComponent('add_product_intent')
    }

    // Max Core Memory
    public coreMemory(): ApiRequest {
        return this.environmentsDetail().addPathComponent('core_memory')
    }

    public coreMemoryDetail(id: CoreMemory['id']): ApiRequest {
        return this.coreMemory().addPathComponent(id)
    }

    public authenticateWizard(): ApiRequest {
        return this.wizard().addPathComponent('authenticate')
    }

    public messagingTemplates(): ApiRequest {
        return this.environments().current().addPathComponent('messaging_templates')
    }

    public messagingTemplate(templateId: MessageTemplate['id']): ApiRequest {
        return this.messagingTemplates().addPathComponent(templateId)
    }

    public messagingCategories(): ApiRequest {
        return this.environments().current().addPathComponent('messaging_categories')
    }

    public messagingCategory(categoryId: string): ApiRequest {
        return this.messagingCategories().addPathComponent(categoryId)
    }

    public messagingPreferences(): ApiRequest {
        return this.environments().current().addPathComponent('messaging_preferences')
    }

    public messagingPreferencesLink(): ApiRequest {
        return this.environments().current().addPathComponent('messaging_preferences').addPathComponent('generate_link')
    }

    public messagingPreferencesOptOuts(): ApiRequest {
        return this.environments().current().addPathComponent('messaging_preferences').addPathComponent('opt_outs')
    }

    public oauthApplicationPublicMetadata(clientId: string): ApiRequest {
        return this.addPathComponent('oauth_application').addPathComponent('metadata').addPathComponent(clientId)
    }

    public hogFlows(): ApiRequest {
        return this.environments().current().addPathComponent('hog_flows')
    }

    public hogFlow(hogFlowId: HogFlow['id']): ApiRequest {
        return this.hogFlows().addPathComponent(hogFlowId)
    }

    public wizard(): ApiRequest {
        return this.addPathComponent('wizard')
    }

    public datasets(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('datasets')
    }

    public dataset(id: string, teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('datasets').addPathComponent(id)
    }

    public datasetItems(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('dataset_items')
    }

    public datasetItem(id: string, teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('dataset_items').addPathComponent(id)
    }

    public evaluationRuns(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('evaluation_runs')
    }

    // Session summary
    public sessionSummary(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('session_summaries')
    }
}

const normalizeUrl = (url: string): string => {
    if (url.indexOf('http') !== 0) {
        if (!url.startsWith('/')) {
            url = '/' + url
        }

        url = url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
    }
    return url
}

const prepareUrl = (url: string): string => {
    let output = normalizeUrl(url)

    const exporterContext = getCurrentExporterData()

    if (exporterContext && exporterContext.accessToken) {
        output =
            output +
            (output.indexOf('?') === -1 ? '?' : '&') +
            encodeParams({
                sharing_access_token: exporterContext.accessToken,
            })
    }

    return output
}

const PROJECT_ID_REGEX = /\/api\/(project|environment)s\/(\w+)(?:$|[/?#])/

const ensureProjectIdNotInvalid = (url: string): void => {
    const projectIdMatch = PROJECT_ID_REGEX.exec(url)
    if (projectIdMatch) {
        const projectId = projectIdMatch[2].trim()
        if (projectId === 'null' || projectId === 'undefined') {
            throw { status: 0, detail: `Cannot make request - ${projectIdMatch[1]} ID is unknown.` }
        }
    }
}

function getSessionId(): string | undefined {
    // get_session_id is not always present e.g. in the toolbar
    // but our typing in the SDK doesn't make this clear
    // TODO when the SDK makes this safe this check can be simplified
    if (typeof posthog?.get_session_id !== 'function') {
        return undefined
    }
    return posthog.get_session_id()
}

function getDistinctId(): string | undefined {
    if (typeof posthog?.get_distinct_id !== 'function') {
        return undefined
    }
    return posthog.get_distinct_id()
}

const api = {
    cspReporting: {
        explain(properties: Record<string, any>): Promise<{ response: string }> {
            return new ApiRequest().cspReportingExplanation().create({ data: { properties } })
        },
    },
    insights: {
        loadInsight(
            shortId: InsightModel['short_id'],
            basic?: boolean,
            refresh?: RefreshType,
            filtersOverride?: DashboardFilter | null,
            variablesOverride?: Record<string, HogQLVariable> | null,
            tileFiltersOverride?: TileFilters | null
        ): Promise<PaginatedResponse<Partial<InsightModel>>> {
            return new ApiRequest()
                .insights()
                .withQueryString(
                    toParams({
                        short_id: encodeURIComponent(shortId),
                        basic,
                        refresh,
                        filters_override: filtersOverride,
                        variables_override: variablesOverride,
                        tile_filters_override: tileFiltersOverride,
                    })
                )
                .get()
        },
        async get(id: number): Promise<InsightModel | null> {
            return await new ApiRequest().insight(id).get()
        },
        async create(data: any): Promise<InsightModel> {
            return await new ApiRequest().insights().create({ data })
        },
        async update(id: number, data: any): Promise<InsightModel> {
            return await new ApiRequest().insight(id).update({ data })
        },
        async cancelQuery(clientQueryId: string, teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()): Promise<void> {
            await new ApiRequest().insightsCancel(teamId).create({ data: { client_query_id: clientQueryId } })
        },
    },

    endpoint: {
        async list(): Promise<CountedPaginatedResponse<EndpointType>> {
            return await new ApiRequest().endpoint().get()
        },
        async get(name: string): Promise<EndpointType> {
            return await new ApiRequest().endpointDetail(name).get()
        },
        async create(data: EndpointRequest): Promise<EndpointType> {
            return await new ApiRequest().endpoint().create({ data })
        },
        async delete(name: string): Promise<void> {
            return await new ApiRequest().endpointDetail(name).delete()
        },
        async update(name: string, data: EndpointRequest): Promise<EndpointType> {
            return await new ApiRequest().endpointDetail(name).update({ data })
        },
        async getLastExecutionTimes(data: EndpointLastExecutionTimesRequest): Promise<Record<string, string>> {
            if (data.names.length === 0) {
                return {}
            }

            const response: QueryStatusResponse = await new ApiRequest()
                .endpoint()
                .lastExecutionTimes()
                .create({ data })
            const result: Record<string, string> = {}
            if (response.query_status?.results) {
                for (const row of response.query_status.results) {
                    if (row && row.length >= 2) {
                        const [name, timestamp] = row
                        if (name && timestamp) {
                            result[name] = timestamp
                        }
                    }
                }
            }

            return result
        },
    },

    featureFlags: {
        async get(id: FeatureFlagType['id']): Promise<FeatureFlagType> {
            return await new ApiRequest().featureFlag(id).get()
        },
        async bulkKeys(ids: FeatureFlagType['id'][]): Promise<{ keys: Record<string, string> }> {
            return await new ApiRequest().featureFlags().withAction('bulk_keys').create({ data: { ids } })
        },
        async createStaticCohort(id: FeatureFlagType['id']): Promise<{ cohort: CohortType }> {
            return await new ApiRequest().featureFlagCreateStaticCohort(id).create()
        },
        async getScheduledChanges(
            teamId: TeamType['id'],
            featureFlagId: FeatureFlagType['id']
        ): Promise<CountedPaginatedResponse<ScheduledChangeType>> {
            return await new ApiRequest().featureFlagScheduledChanges(teamId, featureFlagId).get()
        },
        async createScheduledChange(
            teamId: TeamType['id'],
            data: any
        ): Promise<{ scheduled_change: ScheduledChangeType }> {
            return await new ApiRequest().featureFlagCreateScheduledChange(teamId).create({ data })
        },
        async deleteScheduledChange(
            teamId: TeamType['id'],
            scheduledChangeId: ScheduledChangeType['id']
        ): Promise<{ scheduled_change: ScheduledChangeType }> {
            return await new ApiRequest().featureFlagDeleteScheduledChange(teamId, scheduledChangeId).delete()
        },
        async getStatus(
            teamId: TeamType['id'],
            featureFlagId: FeatureFlagType['id']
        ): Promise<FeatureFlagStatusResponse> {
            return await new ApiRequest().featureFlagStatus(teamId, featureFlagId).get()
        },
    },

    fileSystem: {
        async list({
            parent,
            path,
            depth,
            limit,
            offset,
            orderBy,
            search,
            ref,
            notType,
            type,
            type__startswith,
            createdAtGt,
            createdAtLt,
        }: {
            parent?: string
            path?: string
            depth?: number
            limit?: number
            offset?: number
            orderBy?: string
            search?: string
            ref?: string
            notType?: string
            type?: string
            type__startswith?: string
            createdAtGt?: string
            createdAtLt?: string
        }): Promise<CountedPaginatedResponseWithUsers<FileSystemEntry>> {
            return await new ApiRequest()
                .fileSystem()
                .withQueryString({
                    parent,
                    path,
                    depth,
                    limit,
                    offset,
                    search,
                    ref,
                    type,
                    not_type: notType,
                    order_by: orderBy,
                    type__startswith,
                    created_at__gt: createdAtGt,
                    created_at__lt: createdAtLt,
                })
                .get()
        },
        async unfiled(type?: string): Promise<CountedPaginatedResponse<FileSystemEntry>> {
            return await new ApiRequest().fileSystemUnfiled(type).get()
        },
        async create(data: FileSystemEntry): Promise<FileSystemEntry> {
            return await new ApiRequest().fileSystem().create({ data })
        },
        async update(id: NonNullable<FileSystemEntry['id']>, data: Partial<FileSystemEntry>): Promise<FileSystemEntry> {
            return await new ApiRequest().fileSystemDetail(id).update({ data })
        },
        async delete(id: NonNullable<FileSystemEntry['id']>): Promise<FileSystemEntry> {
            return await new ApiRequest().fileSystemDetail(id).delete()
        },
        async move(id: NonNullable<FileSystemEntry['id']>, newPath: string): Promise<FileSystemEntry> {
            return await new ApiRequest().fileSystemMove(id).create({ data: { new_path: newPath } })
        },
        async link(id: NonNullable<FileSystemEntry['id']>, newPath: string): Promise<FileSystemEntry> {
            return await new ApiRequest().fileSystemLink(id).create({ data: { new_path: newPath } })
        },
        async count(id: NonNullable<FileSystemEntry['id']>): Promise<FileSystemCount> {
            return await new ApiRequest().fileSystemCount(id).create()
        },
    },

    fileSystemShortcuts: {
        async list(): Promise<CountedPaginatedResponse<FileSystemEntry>> {
            return await new ApiRequest().fileSystemShortcut().get()
        },
        async create(data: { path: string; href?: string; ref?: string; type?: string }): Promise<FileSystemEntry> {
            return await new ApiRequest().fileSystemShortcut().create({ data })
        },
        async delete(id: FileSystemEntry['id']): Promise<void> {
            return await new ApiRequest().fileSystemShortcutDetail(id).delete()
        },
    },

    persistedFolder: {
        async list(): Promise<CountedPaginatedResponse<PersistedFolder>> {
            return await new ApiRequest().persistedFolder().get()
        },
        async create(data: { protocol: string; path: string; type?: string }): Promise<PersistedFolder> {
            return await new ApiRequest().persistedFolder().create({ data })
        },
        async delete(id: PersistedFolder['id']): Promise<void> {
            return await new ApiRequest().persistedFolderDetail(id).delete()
        },
    },

    organizationFeatureFlags: {
        async get(
            orgId: OrganizationType['id'] = ApiConfig.getCurrentOrganizationId(),
            featureFlagKey: FeatureFlagType['key']
        ): Promise<OrganizationFeatureFlags> {
            return await new ApiRequest().organizationFeatureFlags(orgId, featureFlagKey).get()
        },
        async copy(
            orgId: OrganizationType['id'] = ApiConfig.getCurrentOrganizationId(),
            data: OrganizationFeatureFlagsCopyBody
        ): Promise<{ success: FeatureFlagType[]; failed: any }> {
            return await new ApiRequest().copyOrganizationFeatureFlags(orgId).create({ data })
        },
    },

    actions: {
        async get(actionId: ActionType['id']): Promise<ActionType> {
            return await new ApiRequest().actionsDetail(actionId).get()
        },
        async create(actionData: Partial<ActionType>, temporaryToken?: string): Promise<ActionType> {
            return await new ApiRequest()
                .actions()
                .withQueryString(temporaryToken ? `temporary_token=${temporaryToken}` : '')
                .create({ data: actionData })
        },
        async update(
            actionId: ActionType['id'],
            actionData: Partial<ActionType>,
            temporaryToken?: string
        ): Promise<ActionType> {
            return await new ApiRequest()
                .actionsDetail(actionId)
                .withQueryString(temporaryToken ? `temporary_token=${temporaryToken}` : '')
                .update({ data: actionData })
        },
        async migrate(id: ActionType['id']): Promise<HogFunctionType> {
            return await new ApiRequest().actionsDetail(id).withAction('migrate').create()
        },
        async list(params?: string): Promise<PaginatedResponse<ActionType>> {
            return await new ApiRequest().actions().withQueryString(params).get()
        },
        async listMatchingPluginConfigs(
            actionId: ActionType['id']
        ): Promise<PaginatedResponse<PluginConfigWithPluginInfoNew>> {
            return await new ApiRequest()
                .actionsDetail(actionId)
                .withAction('plugin_configs')
                .withQueryString({
                    limit: 1000,
                })
                .get()
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().actions().assembleEndpointUrl()
        },
    },

    activity: {
        list(
            filters: Partial<Pick<ActivityLogItem, 'item_id' | 'scope'> & { user?: UserBasicType['id'] }>,
            projectId: ProjectType['id'] = ApiConfig.getCurrentProjectId()
        ): Promise<PaginatedResponse<ActivityLogItem>> {
            return api.activity.listRequest(filters, projectId).get()
        },

        listRequest(
            filters: Partial<{
                scope?: ActivityScope | string
                scopes?: ActivityScope[] | string
                user?: UserBasicType['id']
                page?: number
                page_size?: number
                item_id?: number | string
            }>,
            projectId: ProjectType['id'] = ApiConfig.getCurrentProjectId()
        ): ApiRequest {
            if (Array.isArray(filters.scopes)) {
                filters.scopes = filters.scopes.join(',')
            }
            return new ApiRequest().activityLog(projectId).withQueryString(toParams(filters))
        },

        listLegacy(
            props: ActivityLogProps,
            page: number = 1,
            projectId: ProjectType['id'] = ApiConfig.getCurrentProjectId()
        ): Promise<ActivityLogPaginatedResponse<ActivityLogItem>> {
            const scopes = Array.isArray(props.scope) ? [...props.scope] : [props.scope]

            // Opt into the new /activity_log API
            if (
                [
                    ActivityScope.PLUGIN,
                    ActivityScope.HOG_FUNCTION,
                    ActivityScope.EXPERIMENT,
                    ActivityScope.TAG,
                ].includes(scopes[0]) ||
                scopes.length > 1
            ) {
                return api.activity
                    .listRequest({
                        scopes,
                        ...(props.id ? { item_id: props.id } : {}),
                        page: page || 1,
                        page_size: ACTIVITY_PAGE_SIZE,
                    })
                    .get()
            }

            // TODO: Can we replace all these endpoint specific implementations with the generic REST endpoint above?
            const requestForScope: { [key in ActivityScope]?: () => ApiRequest | null } = {
                [ActivityScope.FEATURE_FLAG]: () => {
                    return new ApiRequest().featureFlagsActivity((props.id ?? null) as number | null, projectId)
                },
                [ActivityScope.PERSON]: () => {
                    return new ApiRequest().personActivity(props.id)
                },
                [ActivityScope.GROUP]: () => {
                    return new ApiRequest().groupActivity()
                },
                [ActivityScope.INSIGHT]: () => {
                    return new ApiRequest().insightsActivity(projectId)
                },
                [ActivityScope.PLUGIN_CONFIG]: () => {
                    return props.id
                        ? new ApiRequest().pluginConfig(props.id as number, projectId).withAction('activity')
                        : new ApiRequest().plugins().withAction('activity')
                },
                [ActivityScope.DATA_MANAGEMENT]: () => {
                    return new ApiRequest().dataManagementActivity()
                },
                [ActivityScope.EVENT_DEFINITION]: () => {
                    // TODO allow someone to load _only_ event definitions?
                    return new ApiRequest().dataManagementActivity()
                },
                [ActivityScope.PROPERTY_DEFINITION]: () => {
                    // TODO allow someone to load _only_ property definitions?
                    return new ApiRequest().dataManagementActivity()
                },
                [ActivityScope.NOTEBOOK]: () => {
                    return props.id
                        ? new ApiRequest().notebook(`${props.id}`).withAction('activity')
                        : new ApiRequest().notebooks().withAction('activity')
                },
                [ActivityScope.TEAM]: () => {
                    return new ApiRequest().projectsDetail().withAction('activity')
                },
                [ActivityScope.SURVEY]: () => {
                    return new ApiRequest().surveyActivity((props.id ?? null) as string, projectId)
                },
                [ActivityScope.DATA_WAREHOUSE_SAVED_QUERY]: () => {
                    return new ApiRequest().dataWarehouseSavedQueryActivity((props.id ?? null) as string, projectId)
                },
            }

            let parameters = { page: page || 1, limit: ACTIVITY_PAGE_SIZE } as Record<string, any>
            const request = requestForScope[scopes[0]]?.()
            // :KLUDGE: Groups don't expose a unique ID so we need to pass the index and the key
            if (scopes[0] === ActivityScope.GROUP && props.id) {
                const groupTypeIndex = (props.id as string)[0]
                const groupKey = (props.id as string).substring(2)
                parameters = { ...parameters, group_type_index: groupTypeIndex, group_key: groupKey }
            }
            return request
                ? request.withQueryString(toParams(parameters)).get()
                : Promise.resolve({ results: [], count: 0 })
        },
    },

    comments: {
        async create(
            data: Partial<CommentType> & CommentCreationParams,
            params: Record<string, any> = {},
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()
        ): Promise<CommentType> {
            return new ApiRequest().comments(teamId).withQueryString(toParams(params)).create({ data })
        },

        async update(
            id: CommentType['id'],
            data: Partial<CommentType> & CommentCreationParams,
            params: Record<string, any> = {},
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()
        ): Promise<CommentType> {
            return new ApiRequest().comment(id, teamId).withQueryString(toParams(params)).update({ data })
        },

        async get(id: CommentType['id'], teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()): Promise<CommentType> {
            return new ApiRequest().comment(id, teamId).get()
        },

        async list(params: Partial<CommentType> = {}): Promise<CountedPaginatedResponse<CommentType>> {
            return new ApiRequest().comments().withQueryString(params).get()
        },

        async getCount(params: Partial<CommentType> & { exclude_emoji_reactions?: boolean }): Promise<number> {
            return (await new ApiRequest().comments().withAction('count').withQueryString(params).get()).count
        },

        async delete(id: CommentType['id'], teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()): Promise<void> {
            return new ApiRequest().comment(id, teamId).update({ data: { deleted: true } })
        },
    },

    logs: {
        async query({
            query,
            signal,
        }: {
            query: Omit<LogsQuery, 'kind'>
            signal?: AbortSignal
        }): Promise<{ results: LogMessage[] }> {
            return new ApiRequest().logsQuery().create({ signal, data: { query } })
        },
        async sparkline({ query, signal }: { query: Omit<LogsQuery, 'kind'>; signal?: AbortSignal }): Promise<any[]> {
            return new ApiRequest().logsSparkline().create({ signal, data: { query } })
        },
    },

    exports: {
        determineExportUrl(exportId: number, teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()): string {
            return new ApiRequest()
                .export(exportId, teamId)
                .withAction('content')
                .withQueryString('download=true')
                .assembleFullUrl(true)
        },

        async create(
            data: Partial<ExportedAssetType>,
            params: Record<string, any> = {},
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()
        ): Promise<ExportedAssetType> {
            return new ApiRequest().exports(teamId).withQueryString(toParams(params)).create({ data })
        },

        async list(
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId(),
            params: Record<string, any> = {}
        ): Promise<PaginatedResponse<ExportedAssetType>> {
            return new ApiRequest().exports(teamId).withQueryString(toParams(params)).get()
        },

        async get(id: number, teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()): Promise<ExportedAssetType> {
            return new ApiRequest().export(id, teamId).get()
        },
    },

    events: {
        async get(
            id: EventType['id'],
            includePerson: boolean = false,
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()
        ): Promise<EventType> {
            let apiRequest = new ApiRequest().event(id, teamId)
            if (includePerson) {
                apiRequest = apiRequest.withQueryString(toParams({ include_person: true }))
            }
            return await apiRequest.get()
        },
        async list(
            filters: EventsListQueryParams,
            limit: number = 100,
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()
        ): Promise<PaginatedResponse<EventType>> {
            const params: EventsListQueryParams = { ...filters, limit, orderBy: filters.orderBy ?? ['-timestamp'] }
            return new ApiRequest().events(teamId).withQueryString(toParams(params)).get()
        },
        determineListEndpoint(
            filters: EventsListQueryParams,
            limit: number = 100,
            teamId: TeamType['id'] = ApiConfig.getCurrentTeamId()
        ): string {
            const params: EventsListQueryParams = { ...filters, limit }
            return new ApiRequest().events(teamId).withQueryString(toParams(params)).assembleFullUrl()
        },
    },

    tags: {
        async list(projectId: TeamType['id'] = ApiConfig.getCurrentProjectId()): Promise<string[]> {
            return new ApiRequest().tags(projectId).get()
        },
    },

    eventDefinitions: {
        async get({ eventDefinitionId }: { eventDefinitionId: EventDefinition['id'] }): Promise<EventDefinition> {
            return new ApiRequest().eventDefinitionDetail(eventDefinitionId).get()
        },
        async update({
            eventDefinitionId,
            eventDefinitionData,
        }: {
            eventDefinitionId: EventDefinition['id']
            eventDefinitionData: Partial<Omit<EventDefinition, 'owner'> & { owner: number | null }>
        }): Promise<EventDefinition> {
            return new ApiRequest().eventDefinitionDetail(eventDefinitionId).update({ data: eventDefinitionData })
        },
        async delete({ eventDefinitionId }: { eventDefinitionId: EventDefinition['id'] }): Promise<void> {
            return new ApiRequest().eventDefinitionDetail(eventDefinitionId).delete()
        },
        async list({
            limit = EVENT_DEFINITIONS_PER_PAGE,
            teamId,
            ...params
        }: {
            limit?: number
            offset?: number
            teamId?: TeamType['id']
            event_type?: EventDefinitionType
            search?: string
        }): Promise<CountedPaginatedResponse<EventDefinition>> {
            return new ApiRequest()
                .eventDefinitions(teamId)
                .withQueryString(toParams({ limit, ...params }))
                .get()
        },
        async getMetrics({
            eventDefinitionId,
        }: {
            eventDefinitionId: EventDefinition['id']
        }): Promise<EventDefinitionMetrics> {
            return new ApiRequest().eventDefinitionDetail(eventDefinitionId).withAction('metrics').get()
        },
        determineListEndpoint({
            limit = EVENT_DEFINITIONS_PER_PAGE,
            teamId,
            ...params
        }: {
            limit?: number
            offset?: number
            teamId?: TeamType['id']
            event_type?: EventDefinitionType
            search?: string
        }): string {
            return new ApiRequest()
                .eventDefinitions(teamId)
                .withQueryString(toParams({ limit, ...params }))
                .assembleFullUrl()
        },
    },

    propertyDefinitions: {
        async get({
            propertyDefinitionId,
        }: {
            propertyDefinitionId: PropertyDefinition['id']
        }): Promise<PropertyDefinition> {
            return new ApiRequest().propertyDefinitionDetail(propertyDefinitionId).get()
        },
        async seenTogether({
            eventNames,
            propertyDefinitionName,
        }: {
            eventNames: string[]
            propertyDefinitionName: PropertyDefinition['name']
        }): Promise<Record<string, boolean>> {
            return new ApiRequest().propertyDefinitionSeenTogether(eventNames, propertyDefinitionName).get()
        },
        async update({
            propertyDefinitionId,
            propertyDefinitionData,
        }: {
            propertyDefinitionId: PropertyDefinition['id']
            propertyDefinitionData: Partial<PropertyDefinition>
        }): Promise<PropertyDefinition> {
            return new ApiRequest()
                .propertyDefinitionDetail(propertyDefinitionId)
                .update({ data: propertyDefinitionData })
        },
        async delete({ propertyDefinitionId }: { propertyDefinitionId: PropertyDefinition['id'] }): Promise<void> {
            return new ApiRequest().propertyDefinitionDetail(propertyDefinitionId).delete()
        },
        async list({
            limit = EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
            teamId,
            ...params
        }: {
            event_names?: string[]
            excluded_properties?: string[]
            exclude_core_properties?: boolean
            properties?: string[]
            filter_by_event_names?: boolean
            type?: PropertyDefinitionType
            limit?: number
            offset?: number
            search?: string
            teamId?: TeamType['id']
        }): Promise<CountedPaginatedResponse<PropertyDefinition>> {
            return new ApiRequest()
                .propertyDefinitions(teamId)
                .withQueryString(
                    toParams({
                        limit,
                        ...params,
                        ...(params.properties ? { properties: params.properties.join(',') } : {}),
                    })
                )
                .get()
        },
        determineListEndpoint({
            limit = EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
            teamId,
            ...params
        }: {
            event_names?: string[]
            excluded_properties?: string[]
            exclude_core_properties?: boolean
            filter_by_event_names?: boolean
            is_feature_flag?: boolean
            limit?: number
            offset?: number
            search?: string
            teamId?: TeamType['id']
            type?: PropertyDefinitionType
            group_type_index?: number
        }): string {
            return new ApiRequest()
                .propertyDefinitions(teamId)
                .withQueryString(
                    toParams({
                        limit,
                        ...params,
                    })
                )
                .assembleFullUrl()
        },
    },

    sessions: {
        async propertyDefinitions({
            teamId,
            search,
            properties,
        }: {
            teamId?: TeamType['id']
            search?: string
            properties?: string[]
        }): Promise<CountedPaginatedResponse<PropertyDefinition>> {
            return new ApiRequest()
                .sessionPropertyDefinitions(teamId)
                .withQueryString(toParams({ search, ...(properties ? { properties: properties.join(',') } : {}) }))
                .get()
        },
    },

    cohorts: {
        async get(cohortId: CohortType['id']): Promise<CohortType> {
            return await new ApiRequest().cohortsDetail(cohortId).get()
        },
        async create(cohortData: Partial<CohortType>, filterParams?: string): Promise<CohortType> {
            return await new ApiRequest().cohorts().withQueryString(filterParams).create({ data: cohortData })
        },
        async update(
            cohortId: CohortType['id'],
            cohortData: Partial<CohortType>,
            filterParams?: string
        ): Promise<CohortType> {
            return await new ApiRequest()
                .cohortsDetail(cohortId)
                .withQueryString(filterParams)
                .update({ data: cohortData })
        },
        async duplicate(cohortId: CohortType['id']): Promise<CohortType> {
            return await new ApiRequest().cohortsDuplicate(cohortId).get()
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().cohorts().assembleEndpointUrl()
        },
        determineListUrl(cohortId: number | 'new', params: PersonListParams): string {
            return `/api/cohort/${cohortId}/persons?${toParams(params)}`
        },
        async listPaginated(
            params: {
                limit?: number
                offset?: number
                search?: string
            } = {}
        ): Promise<CountedPaginatedResponse<CohortType>> {
            return await new ApiRequest().cohorts().withQueryString(toParams(params)).get()
        },
        async getCohortPersons(cohortId: CohortType['id']): Promise<PaginatedResponse<PersonType>> {
            return await new ApiRequest()
                .cohortsDetailPersons(cohortId)
                .withQueryString(toParams({ limit: COHORT_PERSONS_QUERY_LIMIT }))
                .get()
        },
        async addPersonsToStaticCohort(cohortId: CohortType['id'], ids: string[]): Promise<{ success: boolean }> {
            return await new ApiRequest().cohortsAddPersonsToStatic(cohortId).update({ data: { person_ids: ids } })
        },
        async removePersonFromCohort(cohortId: CohortType['id'], personId: string): Promise<{ success: boolean }> {
            const payload = { person_id: personId }
            return await new ApiRequest().cohortsRemovePersonFromStatic(cohortId).update({ data: payload })
        },
        async getCalculationHistory(cohortId: CohortType['id']): Promise<CohortCalculationHistoryResponse> {
            return await new ApiRequest().cohortsCalculationHistory(cohortId).get()
        },
    },

    dashboards: {
        async get(id: number): Promise<DashboardType> {
            return new ApiRequest().dashboardsDetail(id).get()
        },

        async streamTiles(
            id: number,
            params: {
                layoutSize?: 'sm' | 'xs'
                filtersOverride?: DashboardFilter
                variablesOverride?: Record<string, HogQLVariable>
            } = {},
            onMessage: (data: any) => void,
            onComplete: () => void,
            onError: (error: any) => void
        ): Promise<() => void> {
            const url = new ApiRequest()
                .dashboardsDetail(id)
                .withAction('stream_tiles')
                .withQueryString(
                    toParams({
                        layout_size: params.layoutSize,
                        filters_override: params.filtersOverride,
                        variables_override: params.variablesOverride,
                    })
                )
                .assembleFullUrl(true)

            const abortController = new AbortController()

            fetchEventSource(url, {
                signal: abortController.signal,
                credentials: 'include',
                openWhenHidden: true,
                onopen: async (response) => {
                    if (!response.ok) {
                        // Get server error message if available
                        let errorMessage = `HTTP ${response.status}`
                        try {
                            const errorText = await response.text()
                            if (errorText) {
                                errorMessage = `HTTP ${response.status}: ${errorText}`
                            }
                        } catch {
                            // If we can't read the response, just use the status
                        }

                        // For any error, call onError and abort to prevent retries
                        onError(new Error(errorMessage))
                        abortController.abort()
                        return
                    }
                },
                onmessage: (event: EventSourceMessage) => {
                    try {
                        const data = JSON.parse(event.data)
                        if (data.type === 'complete') {
                            onComplete()
                        } else if (data.type === 'error') {
                            onError(new Error(data.error || 'Streaming error'))
                        } else {
                            onMessage(data)
                        }
                    } catch (error) {
                        onError(error)
                    }
                },
                onerror: (error) => {
                    onError(error)
                },
            }).catch(onError)

            return () => abortController.abort()
        },
    },

    dashboardTemplates: {
        async list(params: DashboardTemplateListParams = {}): Promise<PaginatedResponse<DashboardTemplateType>> {
            return await new ApiRequest().dashboardTemplates().withQueryString(toParams(params)).get()
        },

        async get(dashboardTemplateId: DashboardTemplateType['id']): Promise<DashboardTemplateType> {
            return await new ApiRequest().dashboardTemplatesDetail(dashboardTemplateId).get()
        },

        async create(dashboardTemplateData: DashboardTemplateEditorType): Promise<DashboardTemplateType> {
            return await new ApiRequest().dashboardTemplates().create({ data: dashboardTemplateData })
        },

        async update(
            dashboardTemplateId: string,
            dashboardTemplateData: Partial<DashboardTemplateEditorType>
        ): Promise<DashboardTemplateType> {
            return await new ApiRequest()
                .dashboardTemplatesDetail(dashboardTemplateId)
                .update({ data: dashboardTemplateData })
        },

        async delete(dashboardTemplateId: string): Promise<void> {
            // soft delete
            return await new ApiRequest().dashboardTemplatesDetail(dashboardTemplateId).update({
                data: {
                    deleted: true,
                },
            })
        },
        async getSchema(): Promise<Record<string, any>> {
            return await new ApiRequest().dashboardTemplateSchema().get()
        },
        determineSchemaUrl(): string {
            return new ApiRequest().dashboardTemplateSchema().assembleFullUrl()
        },
    },

    experiments: {
        async get(id: number): Promise<Experiment> {
            return new ApiRequest().experimentsDetail(id).get()
        },
        async createExposureCohort(id: number): Promise<{ cohort: CohortType }> {
            return await new ApiRequest().experimentCreateExposureCohort(id).create()
        },
    },

    organizationMembers: {
        async list(params: ListOrganizationMembersParams = {}): Promise<PaginatedResponse<OrganizationMemberType>> {
            return await new ApiRequest().organizationMembers().withQueryString(params).get()
        },

        async listAll(params: ListOrganizationMembersParams = {}): Promise<OrganizationMemberType[]> {
            const url = new ApiRequest().organizationMembers().withQueryString(params).assembleFullUrl()
            return api.loadPaginatedResults<OrganizationMemberType>(url)
        },

        async delete(uuid: OrganizationMemberType['user']['uuid']): Promise<PaginatedResponse<void>> {
            return await new ApiRequest().organizationMember(uuid).delete()
        },

        async update(
            uuid: string,
            data: Partial<Pick<OrganizationMemberType, 'level'>>
        ): Promise<OrganizationMemberType> {
            return new ApiRequest().organizationMember(uuid).update({ data })
        },
        scopedApiKeys: {
            async list(uuid: string): Promise<OrganizationMemberScopedApiKeysResponse> {
                return new ApiRequest().organizationMemberScopedApiKeys(uuid).get()
            },
        },
    },

    roles: {
        async get(roleId: RoleType['id']): Promise<RoleType> {
            return await new ApiRequest().rolesDetail(roleId).get()
        },
        async list(): Promise<PaginatedResponse<RoleType>> {
            return await new ApiRequest().roles().get()
        },
        async delete(roleId: RoleType['id']): Promise<void> {
            return await new ApiRequest().rolesDetail(roleId).delete()
        },
        async create(roleName: RoleType['name']): Promise<RoleType> {
            return await new ApiRequest().roles().create({
                data: {
                    name: roleName,
                },
            })
        },
        async update(roleId: RoleType['id'], roleData: Partial<RoleType>): Promise<RoleType> {
            return await new ApiRequest().rolesDetail(roleId).update({ data: roleData })
        },
        members: {
            async list(roleId: RoleType['id']): Promise<PaginatedResponse<RoleMemberType>> {
                return await new ApiRequest().roleMemberships(roleId).get()
            },
            async create(roleId: RoleType['id'], userUuid: UserType['uuid']): Promise<RoleMemberType> {
                return await new ApiRequest().roleMemberships(roleId).create({
                    data: {
                        user_uuid: userUuid,
                    },
                })
            },
            async get(roleId: RoleType['id'], userUuid: UserType['uuid']): Promise<void> {
                return await new ApiRequest().roleMembershipsDetail(roleId, userUuid).get()
            },
            async delete(roleId: RoleType['id'], userUuid: UserType['uuid']): Promise<void> {
                return await new ApiRequest().roleMembershipsDetail(roleId, userUuid).delete()
            },
        },
    },

    persons: {
        async update(id: number, person: Partial<PersonType>): Promise<PersonType> {
            return new ApiRequest().person(id).update({ data: person })
        },
        async updateProperty(id: string, property: string, value: any): Promise<void> {
            return new ApiRequest()
                .person(id)
                .withAction('update_property')
                .create({
                    data: {
                        key: property,
                        value: value,
                    },
                })
        },
        async deleteProperty(id: string, property: string): Promise<void> {
            return new ApiRequest()
                .person(id)
                .withAction('delete_property')
                .create({
                    data: {
                        $unset: property,
                    },
                })
        },
        async list(params: PersonListParams = {}): Promise<CountedPaginatedResponse<PersonType>> {
            return await new ApiRequest().persons().withQueryString(toParams(params)).get()
        },
        determineListUrl(params: PersonListParams = {}): string {
            return new ApiRequest().persons().withQueryString(toParams(params)).assembleFullUrl()
        },
        async resetPersonDistinctId(distinctId: string): Promise<void> {
            return await new ApiRequest()
                .persons()
                .withAction('reset_person_distinct_id')
                .create({
                    data: {
                        distinct_id: distinctId,
                    },
                })
        },
    },

    groups: {
        async list(params: GroupListParams): Promise<CountedPaginatedResponse<Group>> {
            return await new ApiRequest().groups().withQueryString(toParams(params, true)).get()
        },
        async create(data: CreateGroupParams): Promise<Group> {
            return await new ApiRequest().groups().create({ data })
        },
        async updateProperty(index: number, key: string, property: string, value: any): Promise<void> {
            return new ApiRequest()
                .group(index, key)
                .withAction('update_property')
                .create({
                    data: {
                        key: property,
                        value: value,
                    },
                })
        },
        async deleteProperty(index: number, key: string, property: string): Promise<void> {
            return new ApiRequest()
                .group(index, key)
                .withAction('delete_property')
                .create({
                    data: {
                        $unset: property,
                    },
                })
        },
    },

    search: {
        async list(params: SearchListParams): Promise<SearchResponse> {
            return await new ApiRequest().search().withQueryString(toParams(params, true)).get()
        },
    },

    sharing: {
        async get({
            dashboardId,
            insightId,
            recordingId,
        }: {
            dashboardId?: DashboardType['id']
            insightId?: QueryBasedInsightModel['id']
            recordingId?: SessionRecordingType['id']
        }): Promise<SharingConfigurationType | null> {
            return dashboardId
                ? new ApiRequest().dashboardSharing(dashboardId).get()
                : insightId
                  ? new ApiRequest().insightSharing(insightId).get()
                  : recordingId
                    ? new ApiRequest().recordingSharing(recordingId).get()
                    : null
        },

        async update(
            {
                dashboardId,
                insightId,
                recordingId,
            }: {
                dashboardId?: DashboardType['id']
                insightId?: QueryBasedInsightModel['id']
                recordingId?: SessionRecordingType['id']
            },
            data: Partial<SharingConfigurationType>
        ): Promise<SharingConfigurationType | null> {
            return dashboardId
                ? new ApiRequest().dashboardSharing(dashboardId).update({ data })
                : insightId
                  ? new ApiRequest().insightSharing(insightId).update({ data })
                  : recordingId
                    ? new ApiRequest().recordingSharing(recordingId).update({ data })
                    : null
        },

        async createPassword(
            {
                dashboardId,
                insightId,
                recordingId,
            }: {
                dashboardId?: DashboardType['id']
                insightId?: QueryBasedInsightModel['id']
                recordingId?: SessionRecordingType['id']
            },
            data: { raw_password?: string; note?: string }
        ): Promise<{ id: string; password: string; note: string; created_at: string; created_by_email: string }> {
            return dashboardId
                ? new ApiRequest().dashboardSharingPasswords(dashboardId).create({ data })
                : insightId
                  ? new ApiRequest().insightSharingPasswords(insightId).create({ data })
                  : recordingId
                    ? new ApiRequest().recordingSharingPasswords(recordingId).create({ data })
                    : null
        },

        async deletePassword(
            {
                dashboardId,
                insightId,
                recordingId,
            }: {
                dashboardId?: DashboardType['id']
                insightId?: QueryBasedInsightModel['id']
                recordingId?: SessionRecordingType['id']
            },
            passwordId: string
        ): Promise<void> {
            return dashboardId
                ? new ApiRequest().dashboardSharingPassword(dashboardId, passwordId).delete()
                : insightId
                  ? new ApiRequest().insightSharingPassword(insightId, passwordId).delete()
                  : recordingId
                    ? new ApiRequest().recordingSharingPassword(recordingId, passwordId).delete()
                    : null
        },
    },

    pluginConfigs: {
        async get(id: PluginConfigTypeNew['id']): Promise<PluginConfigWithPluginInfoNew> {
            return await new ApiRequest().pluginConfig(id).get()
        },
        async update(id: PluginConfigTypeNew['id'], data: FormData): Promise<PluginConfigWithPluginInfoNew> {
            return await new ApiRequest().pluginConfig(id).update({ data })
        },
        async create(data: FormData): Promise<PluginConfigWithPluginInfoNew> {
            return await new ApiRequest().pluginConfigs().create({ data })
        },
        async list(): Promise<PaginatedResponse<PluginConfigTypeNew>> {
            return await new ApiRequest().pluginConfigs().get()
        },
        async migrate(id: PluginConfigTypeNew['id']): Promise<HogFunctionType> {
            return await new ApiRequest().pluginConfig(id).withAction('migrate').create()
        },
        async logs(pluginConfigId: number, params: LogEntryRequestParams): Promise<LogEntry[]> {
            const levels = (params.level?.split(',') ?? []).filter((x) => x !== 'WARNING')
            const response = await new ApiRequest()
                .pluginConfig(pluginConfigId)
                .withAction('logs')
                .withQueryString(
                    toParams(
                        {
                            limit: LOGS_PORTION_LIMIT,
                            type_filter: levels,
                            search: params.search,
                            before: params.before,
                            after: params.after,
                        },
                        true
                    )
                )
                .get()

            const results = response.results.map((entry: PluginLogEntry) => ({
                log_source_id: `${entry.plugin_config_id}`,
                instance_id: entry.source,
                timestamp: entry.timestamp,
                level: entry.type,
                message: entry.message,
            }))

            return results
        },
    },
    hog: {
        async create(hog: string, locals?: any[], inRepl?: boolean): Promise<HogCompileResponse> {
            return await new ApiRequest().hog().create({ data: { hog, locals, in_repl: inRepl || false } })
        },
    },
    hogFunctions: {
        async list({
            filter_groups,
            search,
            types,
            limit,
        }: {
            filter_groups?: CyclotronJobFiltersType[]
            search?: string
            types?: HogFunctionTypeType[]
            limit?: number
        }): Promise<CountedPaginatedResponse<HogFunctionType>> {
            return await new ApiRequest()
                .hogFunctions()
                .withQueryString({
                    filter_groups,
                    // NOTE: The API expects "type" as thats the DB level name
                    ...(types ? { type: types.join(',') } : {}),
                    ...(search ? { search } : {}),
                    ...(limit ? { limit } : {}),
                })
                .get()
        },
        async get(id: HogFunctionType['id']): Promise<HogFunctionType> {
            return await new ApiRequest().hogFunction(id).get()
        },
        async create(data: Partial<HogFunctionType>): Promise<HogFunctionType> {
            return await new ApiRequest().hogFunctions().create({ data })
        },
        async update(id: HogFunctionType['id'], data: Partial<HogFunctionType>): Promise<HogFunctionType> {
            return await new ApiRequest().hogFunction(id).update({ data })
        },
        async logs(
            id: HogFunctionType['id'],
            params: LogEntryRequestParams = {}
        ): Promise<PaginatedResponse<LogEntry>> {
            return await new ApiRequest().hogFunction(id).withAction('logs').withQueryString(params).get()
        },
        async metrics(
            id: HogFunctionType['id'],
            params: AppMetricsV2RequestParams = {}
        ): Promise<AppMetricsV2Response> {
            return await new ApiRequest().hogFunction(id).withAction('metrics').withQueryString(params).get()
        },
        async metricsTotals(
            id: HogFunctionType['id'],
            params: Partial<AppMetricsV2RequestParams> = {}
        ): Promise<AppMetricsTotalsV2Response> {
            return await new ApiRequest().hogFunction(id).withAction('metrics/totals').withQueryString(params).get()
        },
        async listTemplates(params: {
            types: HogFunctionTypeType[]
        }): Promise<PaginatedResponse<HogFunctionTemplateType>> {
            const finalParams = {
                ...params,
                limit: 500,
                types: params.types.join(','),
            }

            return new ApiRequest().hogFunctionTemplates().withQueryString(finalParams).get()
        },
        async getTemplate(id: HogFunctionTemplateType['id']): Promise<HogFunctionTemplateType> {
            return await new ApiRequest().hogFunctionTemplate(id).get()
        },

        async listIcons(params: { query?: string } = {}): Promise<HogFunctionIconResponse[]> {
            return await new ApiRequest().hogFunctions().withAction('icons').withQueryString(params).get()
        },

        async createTestInvocation(
            id: HogFunctionType['id'],
            data: {
                configuration: Record<string, any>
                mock_async_functions: boolean
                globals?: any
                clickhouse_event?: any
                invocation_id?: string
            }
        ): Promise<CyclotronJobTestInvocationResult> {
            return await new ApiRequest().hogFunction(id).withAction('invocations').create({ data })
        },

        async getStatus(id: HogFunctionType['id']): Promise<HogFunctionStatus> {
            return await new ApiRequest().hogFunction(id).withAction('status').get()
        },
        async rearrange(orders: Record<string, number>): Promise<HogFunctionType[]> {
            return await new ApiRequest().hogFunctions().withAction('rearrange').update({ data: { orders } })
        },
    },

    links: {
        async list(
            args: {
                limit?: number
                offset?: number
                search?: string
            } = {
                limit: LINK_PAGE_SIZE,
            }
        ): Promise<CountedPaginatedResponse<LinkType>> {
            return await new ApiRequest().links().withQueryString(args).get()
        },
        async get(id: LinkType['id']): Promise<LinkType> {
            return await new ApiRequest().link(id).get()
        },
        async create(data: Partial<LinkType>): Promise<LinkType> {
            return await new ApiRequest().links().create({ data })
        },
        async update(id: LinkType['id'], data: Partial<LinkType>): Promise<LinkType> {
            return await new ApiRequest().link(id).update({ data })
        },
        async delete(id: LinkType['id']): Promise<void> {
            await new ApiRequest().link(id).delete()
        },
    },

    annotations: {
        async get(annotationId: RawAnnotationType['id']): Promise<RawAnnotationType> {
            return await new ApiRequest().annotation(annotationId).get()
        },
        async update(
            annotationId: RawAnnotationType['id'],
            data: Pick<RawAnnotationType, 'date_marker' | 'scope' | 'content' | 'dashboard_item' | 'dashboard_id'>
        ): Promise<RawAnnotationType> {
            return await new ApiRequest().annotation(annotationId).update({ data })
        },
        async list(params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<RawAnnotationType>> {
            return await new ApiRequest()
                .annotations()
                .withQueryString({
                    limit: params?.limit,
                    offset: params?.offset,
                })
                .get()
        },
        async create(
            data: Pick<RawAnnotationType, 'date_marker' | 'scope' | 'content' | 'dashboard_item' | 'dashboard_id'>
        ): Promise<RawAnnotationType> {
            return await new ApiRequest().annotations().create({ data })
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().annotations().assembleEndpointUrl()
        },
    },

    errorTracking: {
        async getIssue(id: ErrorTrackingIssue['id'], fingerprint?: string): Promise<ErrorTrackingRelationalIssue> {
            return await new ApiRequest().errorTrackingIssue(id).withQueryString(toParams({ fingerprint })).get()
        },

        async updateIssue(
            id: ErrorTrackingIssue['id'],
            data: Partial<Pick<ErrorTrackingIssue, 'status' | 'name' | 'description'>>
        ): Promise<ErrorTrackingRelationalIssue> {
            return await new ApiRequest().errorTrackingIssue(id).update({ data })
        },

        async assignIssue(
            id: ErrorTrackingIssue['id'],
            assignee: ErrorTrackingIssue['assignee']
        ): Promise<{ content: string }> {
            return await new ApiRequest().errorTrackingAssignIssue(id).update({ data: { assignee } })
        },

        async bulkMarkStatus(
            ids: ErrorTrackingIssue['id'][],
            status: ErrorTrackingIssue['status']
        ): Promise<{ content: string }> {
            return await new ApiRequest()
                .errorTrackingIssueBulk()
                .create({ data: { action: 'set_status', ids, status: status } })
        },

        async bulkAssign(
            ids: ErrorTrackingIssue['id'][],
            assignee: ErrorTrackingIssue['assignee']
        ): Promise<{ content: string }> {
            return await new ApiRequest().errorTrackingIssueBulk().create({ data: { action: 'assign', ids, assignee } })
        },

        async mergeInto(
            primaryIssueId: ErrorTrackingIssue['id'],
            mergingIssueIds: ErrorTrackingIssue['id'][]
        ): Promise<{ content: string }> {
            return await new ApiRequest()
                .errorTrackingIssueMerge(primaryIssueId)
                .create({ data: { ids: mergingIssueIds } })
        },

        async split(
            issueId: ErrorTrackingIssue['id'],
            fingerprints: string[],
            exclusive: boolean
        ): Promise<{ content: string }> {
            return await new ApiRequest()
                .errorTrackingIssueSplit(issueId)
                .create({ data: { fingerprints: fingerprints, exclusive } })
        },

        fingerprints: {
            async list(issueId: ErrorTrackingIssue['id']): Promise<CountedPaginatedResponse<ErrorTrackingFingerprint>> {
                const queryString = { issue_id: issueId }
                return await new ApiRequest()
                    .errorTrackingIssueFingerprints()
                    .withQueryString(toParams(queryString))
                    .get()
            },
        },

        symbolSets: {
            async list({
                status,
                offset = 0,
                limit = 100,
            }: {
                status?: SymbolSetStatusFilter
                offset: number
                limit: number
            }): Promise<CountedPaginatedResponse<ErrorTrackingSymbolSet>> {
                const queryString = { order_by: '-created_at', status, offset, limit }
                return await new ApiRequest().errorTrackingSymbolSets().withQueryString(toParams(queryString)).get()
            },

            async update(id: ErrorTrackingSymbolSet['id'], data: FormData): Promise<void> {
                return await new ApiRequest().errorTrackingSymbolSet(id).update({ data })
            },

            async delete(id: ErrorTrackingSymbolSet['id']): Promise<void> {
                return await new ApiRequest().errorTrackingSymbolSet(id).delete()
            },
        },

        async symbolSetStackFrames(
            id: ErrorTrackingSymbolSet['id']
        ): Promise<{ results: ErrorTrackingStackFrameRecord[] }> {
            return await new ApiRequest().errorTrackingStackFrames().create({ data: { symbol_set: id } })
        },

        async stackFrames(
            raw_ids: ErrorTrackingStackFrame['raw_id'][]
        ): Promise<{ results: ErrorTrackingStackFrameRecord[] }> {
            return await new ApiRequest().errorTrackingStackFrames().create({ data: { raw_ids: raw_ids } })
        },

        async rules(ruleType: ErrorTrackingRuleType): Promise<{ results: ErrorTrackingRule[] }> {
            return await new ApiRequest().errorTrackingRules(ruleType).get()
        },

        async createRule(
            ruleType: ErrorTrackingRuleType,
            { id: _, ...data }: ErrorTrackingRule
        ): Promise<ErrorTrackingRule> {
            return await new ApiRequest().errorTrackingRules(ruleType).create({ data })
        },

        async updateRule(ruleType: ErrorTrackingRuleType, { id, ...data }: ErrorTrackingRule): Promise<void> {
            return await new ApiRequest().errorTrackingRule(ruleType, id).update({ data })
        },

        async deleteRule(ruleType: ErrorTrackingRuleType, id: ErrorTrackingRule['id']): Promise<void> {
            return await new ApiRequest().errorTrackingRule(ruleType, id).delete()
        },

        async reorderRules(ruleType: ErrorTrackingRuleType, orders: Record<string, number>): Promise<void> {
            return await new ApiRequest().errorTrackingReorderRules(ruleType).update({ data: { orders } })
        },

        async createExternalReference(
            issueId: string,
            integrationId: number,
            config: Record<string, string>
        ): Promise<ErrorTrackingExternalReference> {
            return await new ApiRequest()
                .errorTrackingExternalReference()
                .create({ data: { integration_id: integrationId, issue: issueId, config } })
        },

        async getSimilarIssues(
            issueId: ErrorTrackingIssue['id']
        ): Promise<Array<{ id: string; title: string; description: string }>> {
            return await new ApiRequest().errorTrackingSimilarIssues(issueId).get()
        },
    },

    recordings: {
        async list(params: RecordingsQuery): Promise<RecordingsQueryResponse> {
            return await new ApiRequest().recordings().withQueryString(toParams(params)).get()
        },
        async getMatchingEvents(params: string): Promise<{ results: string[] }> {
            return await new ApiRequest().recordingMatchingEvents().withQueryString(params).get()
        },
        async get(
            recordingId: SessionRecordingType['id'],
            params: Record<string, any> = {},
            headers: Record<string, string> = {}
        ): Promise<SessionRecordingType> {
            return await new ApiRequest().recording(recordingId).withQueryString(toParams(params)).get({ headers })
        },
        async update(
            recordingId: SessionRecordingType['id'],
            data: Partial<SessionRecordingUpdateType>
        ): Promise<SessionRecordingType> {
            return await new ApiRequest().recording(recordingId).update({ data })
        },

        async persist(recordingId: SessionRecordingType['id']): Promise<{ success: boolean }> {
            return await new ApiRequest().recording(recordingId).withAction('persist').create()
        },

        async summarizeStream(recordingId: SessionRecordingType['id']): Promise<Response> {
            return await api.createResponse(
                new ApiRequest().recording(recordingId).withAction('summarize').assembleFullUrl(),
                // No data to provide except for the recording id.
                // Could be extended later with the state of the filters to better understand the user's intent.
                undefined,
                // TODO: Understand if I need to provide any signal data here
                {}
            )
        },

        async similarRecordings(recordingId: SessionRecordingType['id']): Promise<[string, number][]> {
            return await new ApiRequest().recording(recordingId).withAction('similar_sessions').get()
        },

        async delete(recordingId: SessionRecordingType['id']): Promise<{ success: boolean }> {
            return await new ApiRequest().recording(recordingId).delete()
        },

        async listSnapshotSources(
            recordingId: SessionRecordingType['id'],
            params: Record<string, any> = {},
            headers: Record<string, string> = {}
        ): Promise<SessionRecordingSnapshotResponse> {
            if (params.source) {
                throw new Error('source parameter is not allowed in listSnapshotSources, this is a development error')
            }
            return await new ApiRequest()
                .recording(recordingId)
                .withAction('snapshots')
                .withQueryString(params)
                .get({ headers })
        },

        async getSnapshots(
            recordingId: SessionRecordingType['id'],
            params: SessionRecordingSnapshotParams,
            headers: Record<string, string> = {}
        ): Promise<string[] | Uint8Array> {
            const response = await new ApiRequest()
                .recording(recordingId)
                .withAction('snapshots')
                .withQueryString(params)
                .getResponse({ headers })

            const contentBuffer = new Uint8Array(await response.arrayBuffer())

            // If client requested uncompressed data (decompress=false), return binary data
            if (params.decompress === false) {
                return contentBuffer
            }

            // Otherwise try to decode as text
            try {
                const textDecoder = new TextDecoder()
                const textLines = textDecoder.decode(contentBuffer)

                if (textLines) {
                    const lines = textLines.split('\n')
                    return lines
                }
            } catch (error) {
                console.error('Failed to decode snapshot response as text:', error)
            }
            return []
        },

        async listPlaylists(params: string): Promise<SavedSessionRecordingPlaylistsResult> {
            return await new ApiRequest().recordingPlaylists().withQueryString(params).get()
        },
        async getPlaylist(playlistId: SessionRecordingPlaylistType['short_id']): Promise<SessionRecordingPlaylistType> {
            return await new ApiRequest().recordingPlaylist(playlistId).get()
        },
        async playlistViewed(playlistId: SessionRecordingPlaylistType['short_id']): Promise<void> {
            return await new ApiRequest().recordingPlaylist(playlistId).withAction('playlist_viewed').create()
        },
        async createPlaylist(playlist: Partial<SessionRecordingPlaylistType>): Promise<SessionRecordingPlaylistType> {
            return await new ApiRequest().recordingPlaylists().create({ data: playlist })
        },
        async updatePlaylist(
            playlistId: SessionRecordingPlaylistType['short_id'],
            playlist: Partial<SessionRecordingPlaylistType>
        ): Promise<SessionRecordingPlaylistType> {
            return await new ApiRequest().recordingPlaylist(playlistId).update({ data: playlist })
        },

        async listPlaylistRecordings(
            playlistId: SessionRecordingPlaylistType['short_id'],
            params: Record<string, any> = {}
        ): Promise<RecordingsQueryResponse> {
            return await new ApiRequest()
                .recordingPlaylist(playlistId)
                .withAction('recordings')
                .withQueryString(toParams(params))
                .get()
        },

        async addRecordingToPlaylist(
            playlistId: SessionRecordingPlaylistType['short_id'],
            session_recording_id: SessionRecordingType['id']
        ): Promise<SessionRecordingPlaylistType> {
            return await new ApiRequest()
                .recordingPlaylist(playlistId)
                .withAction('recordings')
                .withAction(session_recording_id)
                .create()
        },

        async bulkAddRecordingsToPlaylist(
            playlistId: SessionRecordingPlaylistType['short_id'],
            session_recording_ids: SessionRecordingType['id'][]
        ): Promise<{ success: boolean; added_count: number; total_requested: number }> {
            return await new ApiRequest()
                .recordingPlaylist(playlistId)
                .withAction('recordings')
                .withAction('bulk_add')
                .create({ data: { session_recording_ids } })
        },

        async bulkDeleteRecordingsFromPlaylist(
            playlistId: SessionRecordingPlaylistType['short_id'],
            session_recording_ids: SessionRecordingType['id'][]
        ): Promise<{ success: boolean; added_count: number; total_requested: number }> {
            return await new ApiRequest()
                .recordingPlaylist(playlistId)
                .withAction('recordings')
                .withAction('bulk_delete')
                .create({ data: { session_recording_ids } })
        },

        async removeRecordingFromPlaylist(
            playlistId: SessionRecordingPlaylistType['short_id'],
            session_recording_id: SessionRecordingType['id']
        ): Promise<SessionRecordingPlaylistType> {
            return await new ApiRequest()
                .recordingPlaylist(playlistId)
                .withAction('recordings')
                .withAction(session_recording_id)
                .delete()
        },

        async aiRegex(regex: string): Promise<{ result: string; data: any }> {
            return await new ApiRequest().recordings().withAction('ai/regex').create({ data: { regex } })
        },

        async bulkDeleteRecordings(session_recording_ids: SessionRecordingType['id'][]): Promise<{
            success: boolean
            deleted_count: number
            total_requested: number
        }> {
            return await new ApiRequest()
                .recordings()
                .withAction('bulk_delete')
                .create({ data: { session_recording_ids } })
        },

        async bulkViewedRecordings(session_recording_ids: SessionRecordingType['id'][]): Promise<{
            success: boolean
            viewed_count: number
            total_requested: number
        }> {
            return await new ApiRequest()
                .recordings()
                .withAction('bulk_viewed')
                .create({ data: { session_recording_ids } })
        },

        async bulkNotViewedRecordings(session_recording_ids: SessionRecordingType['id'][]): Promise<{
            success: boolean
            not_viewed_count: number
            total_requested: number
        }> {
            return await new ApiRequest()
                .recordings()
                .withAction('bulk_not_viewed')
                .create({ data: { session_recording_ids } })
        },
    },

    notebooks: {
        async get(
            notebookId: NotebookType['short_id'],
            params: Record<string, any> = {},
            headers: Record<string, any> = {}
        ): Promise<NotebookType> {
            return await new ApiRequest().notebook(notebookId).withQueryString(toParams(params)).get({
                headers,
            })
        },
        async update(
            notebookId: NotebookType['short_id'],
            data: Partial<Pick<NotebookType, 'version' | 'content' | 'text_content' | 'title' | '_create_in_folder'>>
        ): Promise<NotebookType> {
            return await new ApiRequest().notebook(notebookId).update({ data })
        },
        async list(
            params: {
                contains?: NotebookNodeResource[]
                created_by?: UserBasicType['uuid']
                search?: string
                order?: string
                offset?: number
                limit?: number
            } = {}
        ): Promise<CountedPaginatedResponse<NotebookListItemType>> {
            // TODO attrs could be a union of types like NotebookNodeRecordingAttributes
            const apiRequest = new ApiRequest().notebooks()
            const { contains, ...queryParams } = objectClean(params)

            const newQueryParams: Omit<typeof params, 'contains'> & { contains?: string } = queryParams
            if (contains?.length) {
                const containsString =
                    contains
                        .map(({ type, attrs }) => {
                            const target = type.replace(/^ph-/, '')
                            const match = attrs['id'] ? `:${attrs['id']}` : ''
                            return `${target}${match}`
                        })
                        .join(',') || undefined

                newQueryParams['contains'] = containsString
            }

            return await apiRequest.withQueryString(newQueryParams).get()
        },
        async recordingComments(recordingId: string): Promise<{ results: RecordingComment[] }> {
            return await new ApiRequest()
                .notebooks()
                .withAction('recording_comments')
                .withQueryString({ recording_id: recordingId })
                .get()
        },
        async create(
            data?: Pick<NotebookType, 'content' | 'text_content' | 'title' | '_create_in_folder'>
        ): Promise<NotebookType> {
            return await new ApiRequest().notebooks().create({ data })
        },
        async delete(notebookId: NotebookType['short_id']): Promise<NotebookType> {
            return await new ApiRequest().notebook(notebookId).delete()
        },
    },

    batchExports: {
        async list(params: Record<string, any> = {}): Promise<CountedPaginatedResponse<BatchExportConfiguration>> {
            return await new ApiRequest().batchExports().withQueryString(toParams(params)).get()
        },
        async get(id: BatchExportConfiguration['id']): Promise<BatchExportConfiguration> {
            return await new ApiRequest().batchExport(id).get()
        },
        async update(
            id: BatchExportConfiguration['id'],
            data: Partial<BatchExportConfiguration>
        ): Promise<BatchExportConfiguration> {
            return await new ApiRequest().batchExport(id).update({ data })
        },
        async create(data?: Partial<BatchExportConfiguration>): Promise<BatchExportConfiguration> {
            return await new ApiRequest().batchExports().create({ data })
        },
        async delete(id: BatchExportConfiguration['id']): Promise<BatchExportConfiguration> {
            return await new ApiRequest().batchExport(id).delete()
        },
        async pause(id: BatchExportConfiguration['id']): Promise<BatchExportConfiguration> {
            return await new ApiRequest().batchExport(id).withAction('pause').create()
        },
        async unpause(id: BatchExportConfiguration['id']): Promise<BatchExportConfiguration> {
            return await new ApiRequest().batchExport(id).withAction('unpause').create()
        },
        async listRuns(
            id: BatchExportConfiguration['id'],
            params: Record<string, any> = {}
        ): Promise<PaginatedResponse<RawBatchExportRun>> {
            return await new ApiRequest().batchExportRuns(id).withQueryString(toParams(params)).get()
        },
        async createBackfill(
            id: BatchExportConfiguration['id'],
            data: Pick<BatchExportConfiguration, 'start_at' | 'end_at'>
        ): Promise<BatchExportRun> {
            return await new ApiRequest().batchExport(id).withAction('backfill').create({ data })
        },
        async listBackfills(
            id: BatchExportConfiguration['id'],
            params: Record<string, any> = {}
        ): Promise<PaginatedResponse<RawBatchExportBackfill>> {
            return await new ApiRequest().batchExportBackfills(id).withQueryString(toParams(params)).get()
        },
        async cancelBackfill(
            id: BatchExportConfiguration['id'],
            backfillId: BatchExportBackfill['id'],
            teamId?: TeamType['id']
        ): Promise<BatchExportBackfill> {
            return await new ApiRequest().batchExportBackfill(id, backfillId, teamId).withAction('cancel').create()
        },
        async retryRun(
            id: BatchExportConfiguration['id'],
            runId: BatchExportRun['id'],
            teamId?: TeamType['id']
        ): Promise<BatchExportRun> {
            return await new ApiRequest().batchExportRun(id, runId, teamId).withAction('retry').create()
        },
        async cancelRun(
            id: BatchExportConfiguration['id'],
            runId: BatchExportRun['id'],
            teamId?: TeamType['id']
        ): Promise<BatchExportRun> {
            return await new ApiRequest().batchExportRun(id, runId, teamId).withAction('cancel').create()
        },
        async logs(
            id: BatchExportConfiguration['id'],
            params: LogEntryRequestParams = {}
        ): Promise<PaginatedResponse<LogEntry>> {
            return await new ApiRequest().batchExport(id).withAction('logs').withQueryString(params).get()
        },
        async test(destination: BatchExportService['type']): Promise<BatchExportConfigurationTest> {
            return await new ApiRequest().batchExports().withAction('test').withQueryString({ destination }).get()
        },
        async runTestStep(
            id: BatchExportConfiguration['id'],
            step: number,
            data: Record<string, any>
        ): Promise<BatchExportConfigurationTestStep> {
            return await new ApiRequest()
                .batchExport(id)
                .withAction('run_test_step')
                .create({ data: { step: step, ...data } })
        },
        async runTestStepNew(step: number, data: Record<string, any>): Promise<BatchExportConfigurationTestStep> {
            return await new ApiRequest()
                .batchExports()
                .withAction('run_test_step_new')
                .create({ data: { step: step, ...data } })
        },
    },

    earlyAccessFeatures: {
        async get(featureId: EarlyAccessFeatureType['id']): Promise<EarlyAccessFeatureType> {
            return await new ApiRequest().earlyAccessFeature(featureId).get()
        },
        async create(data: NewEarlyAccessFeatureType): Promise<EarlyAccessFeatureType> {
            return await new ApiRequest().earlyAccessFeatures().create({ data })
        },
        async delete(featureId: EarlyAccessFeatureType['id']): Promise<void> {
            await new ApiRequest().earlyAccessFeature(featureId).delete()
        },
        async update(
            featureId: EarlyAccessFeatureType['id'],
            data: Pick<EarlyAccessFeatureType, 'name' | 'description' | 'stage' | 'documentation_url'>
        ): Promise<EarlyAccessFeatureType> {
            return await new ApiRequest().earlyAccessFeature(featureId).update({ data })
        },
        async list(): Promise<PaginatedResponse<EarlyAccessFeatureType>> {
            return await new ApiRequest().earlyAccessFeatures().get()
        },
    },

    userInterviews: {
        async list(): Promise<PaginatedResponse<UserInterviewType>> {
            return await new ApiRequest().userInterviews().get()
        },
        async get(id: UserInterviewType['id']): Promise<UserInterviewType> {
            return await new ApiRequest().userInterview(id).get()
        },
        async update(
            id: UserInterviewType['id'],
            data: Pick<UserInterviewType, 'summary'>
        ): Promise<UserInterviewType> {
            return await new ApiRequest().userInterview(id).update({ data })
        },
    },

    users: {
        async list(email?: string): Promise<PaginatedResponse<UserType>> {
            return await new ApiRequest().users(email).get()
        },
    },

    tasks: {
        async list(): Promise<PaginatedResponse<Task>> {
            return await new ApiRequest().tasks().get()
        },
        async get(id: Task['id']): Promise<Task> {
            return await new ApiRequest().task(id).get()
        },
        async create(data: TaskUpsertProps): Promise<Task> {
            return await new ApiRequest().tasks().create({ data })
        },
        async update(id: string, data: Partial<TaskUpsertProps>): Promise<Partial<Task>> {
            return await new ApiRequest().task(id).update({ data })
        },
        async delete(id: Task['id']): Promise<void> {
            return await new ApiRequest().task(id).delete()
        },
        async bulkReorder(columns: Record<string, string[]>): Promise<{ updated: number; tasks: Task[] }> {
            return await new ApiRequest().tasks().withAction('bulk_reorder').create({ data: { columns } })
        },
        async run(id: Task['id']): Promise<Task> {
            return await new ApiRequest().task(id).withAction('run').create()
        },
    },

    surveys: {
        async list(
            args: {
                limit?: number
                offset?: number
                search?: string
            } = {
                limit: SURVEY_PAGE_SIZE,
            }
        ): Promise<CountedPaginatedResponse<Survey>> {
            return await new ApiRequest().surveys().withQueryString(args).get()
        },
        async get(surveyId: Survey['id']): Promise<Survey> {
            return await new ApiRequest().survey(surveyId).get()
        },
        async create(data: Partial<Survey>, teamId?: TeamType['id']): Promise<Survey> {
            return await new ApiRequest().surveys(teamId).create({ data })
        },
        async delete(surveyId: Survey['id']): Promise<void> {
            await new ApiRequest().survey(surveyId).delete()
        },
        async update(surveyId: Survey['id'], data: Partial<Survey>): Promise<Survey> {
            return await new ApiRequest().survey(surveyId).update({ data })
        },
        async getResponsesCount(): Promise<{ [key: string]: number }> {
            return await new ApiRequest().surveysResponsesCount().get()
        },
        async summarize_responses(
            surveyId: Survey['id'],
            questionIndex: number | undefined,
            questionId: string | undefined
        ): Promise<any> {
            const apiRequest = new ApiRequest().survey(surveyId).withAction('summarize_responses')
            const queryParams: Record<string, string> = {}

            if (questionIndex !== undefined) {
                queryParams['question_index'] = questionIndex.toString()
            }
            if (questionId !== undefined) {
                queryParams['question_id'] = questionId
            }
            return await apiRequest.withQueryString(queryParams).create()
        },
        async getSurveyStats({
            surveyId,
            dateFrom = null,
            dateTo = null,
        }: {
            surveyId: Survey['id']
            dateFrom?: string | null
            dateTo?: string | null
        }): Promise<
            SurveyStatsResponse & {
                survey_id: string
                start_date: string
                end_date?: string
            }
        > {
            const apiRequest = new ApiRequest().survey(surveyId).withAction('stats')
            const queryParams: Record<string, string> = {}
            if (dateFrom) {
                queryParams['date_from'] = dateFrom
            }
            if (dateTo) {
                queryParams['date_to'] = dateTo
            }

            return await apiRequest.withQueryString(queryParams).get()
        },
        async getGlobalSurveyStats({
            dateFrom = null,
            dateTo = null,
        }: {
            dateFrom?: string | null
            dateTo?: string | null
        }): Promise<SurveyStatsResponse> {
            const apiRequest = new ApiRequest().surveys().withAction('stats')
            const queryParams: Record<string, string> = {}
            if (dateFrom) {
                queryParams['date_from'] = dateFrom
            }
            if (dateTo) {
                queryParams['date_to'] = dateTo
            }
            return await apiRequest.get()
        },
    },

    dataWarehouseTables: {
        async list(): Promise<PaginatedResponse<DataWarehouseTable>> {
            return await new ApiRequest().dataWarehouseTables().get()
        },
        async get(tableId: DataWarehouseTable['id']): Promise<DataWarehouseTable> {
            return await new ApiRequest().dataWarehouseTable(tableId).get()
        },
        async create(data: Partial<DataWarehouseTable>): Promise<DataWarehouseTable> {
            return await new ApiRequest().dataWarehouseTables().create({ data })
        },
        async delete(tableId: DataWarehouseTable['id']): Promise<void> {
            await new ApiRequest().dataWarehouseTable(tableId).delete()
        },
        async update(
            tableId: DataWarehouseTable['id'],
            data: Pick<DataWarehouseTable, 'name'>
        ): Promise<DataWarehouseTable> {
            return await new ApiRequest().dataWarehouseTable(tableId).update({ data })
        },
        async updateSchema(
            tableId: DataWarehouseTable['id'],
            updates: Record<string, DatabaseSerializedFieldType>
        ): Promise<void> {
            await new ApiRequest().dataWarehouseTable(tableId).withAction('update_schema').create({ data: { updates } })
        },
        async refreshSchema(tableId: DataWarehouseTable['id']): Promise<void> {
            await new ApiRequest().dataWarehouseTable(tableId).withAction('refresh_schema').create()
        },
    },

    dataWarehouseSavedQueries: {
        async list(): Promise<PaginatedResponse<DataWarehouseSavedQuery>> {
            return await new ApiRequest().dataWarehouseSavedQueries().get()
        },
        async get(viewId: DataWarehouseSavedQuery['id']): Promise<DataWarehouseSavedQuery> {
            return await new ApiRequest().dataWarehouseSavedQuery(viewId).get()
        },
        async create(data: Partial<DataWarehouseSavedQuery> & { types: string[][] }): Promise<DataWarehouseSavedQuery> {
            return await new ApiRequest().dataWarehouseSavedQueries().create({ data })
        },
        async delete(viewId: DataWarehouseSavedQuery['id']): Promise<void> {
            await new ApiRequest().dataWarehouseSavedQuery(viewId).delete()
        },
        async update(
            viewId: DataWarehouseSavedQuery['id'],
            data: Partial<DataWarehouseSavedQuery> & { types: string[][]; edited_history_id?: string }
        ): Promise<DataWarehouseSavedQuery> {
            return await new ApiRequest().dataWarehouseSavedQuery(viewId).update({ data })
        },
        async run(viewId: DataWarehouseSavedQuery['id']): Promise<void> {
            return await new ApiRequest().dataWarehouseSavedQuery(viewId).withAction('run').create()
        },
        async cancel(viewId: DataWarehouseSavedQuery['id']): Promise<void> {
            return await new ApiRequest().dataWarehouseSavedQuery(viewId).withAction('cancel').create()
        },
        async revertMaterialization(viewId: DataWarehouseSavedQuery['id']): Promise<void> {
            return await new ApiRequest().dataWarehouseSavedQuery(viewId).withAction('revert_materialization').create()
        },
        async ancestors(viewId: DataWarehouseSavedQuery['id'], level?: number): Promise<Record<string, string[]>> {
            return await new ApiRequest()
                .dataWarehouseSavedQuery(viewId)
                .withAction('ancestors')
                .create({ data: { level } })
        },
        async descendants(viewId: DataWarehouseSavedQuery['id'], level?: number): Promise<Record<string, string[]>> {
            return await new ApiRequest()
                .dataWarehouseSavedQuery(viewId)
                .withAction('descendants')
                .create({ data: { level } })
        },
        dataWarehouseDataModelingJobs: {
            async list(
                savedQueryId: DataWarehouseSavedQuery['id'],
                pageSize: number,
                offset: number
            ): Promise<PaginatedResponse<DataModelingJob>> {
                return await new ApiRequest().dataWarehouseDataModelingJobs(savedQueryId, pageSize, offset).get()
            },
        },
    },

    dataWarehouseSavedQueryDrafts: {
        async list(): Promise<PaginatedResponse<DataWarehouseSavedQueryDraft>> {
            return await new ApiRequest().dataWarehouseSavedQueryDrafts().get()
        },
        async get(id: DataWarehouseSavedQueryDraft['id']): Promise<DataWarehouseSavedQueryDraft> {
            return await new ApiRequest().dataWarehouseSavedQueryDraft(id).get()
        },
        async create(data: Partial<DataWarehouseSavedQueryDraft>): Promise<DataWarehouseSavedQueryDraft> {
            return await new ApiRequest().dataWarehouseSavedQueryDrafts().create({ data })
        },
        async delete(id: DataWarehouseSavedQueryDraft['id']): Promise<void> {
            await new ApiRequest().dataWarehouseSavedQueryDraft(id).delete()
        },
        async update(
            id: DataWarehouseSavedQueryDraft['id'],
            data: Partial<DataWarehouseSavedQueryDraft>
        ): Promise<DataWarehouseSavedQueryDraft> {
            return await new ApiRequest().dataWarehouseSavedQueryDraft(id).update({ data })
        },
    },

    externalDataSources: {
        async list(options?: ApiMethodOptions | undefined): Promise<PaginatedResponse<ExternalDataSource>> {
            return await new ApiRequest().externalDataSources().get(options)
        },
        async get(sourceId: ExternalDataSource['id']): Promise<ExternalDataSource> {
            return await new ApiRequest().externalDataSource(sourceId).get()
        },
        async create(data: Partial<ExternalDataSourceCreatePayload>): Promise<{ id: string }> {
            return await new ApiRequest().externalDataSources().create({ data })
        },
        async delete(sourceId: ExternalDataSource['id']): Promise<void> {
            await new ApiRequest().externalDataSource(sourceId).delete()
        },
        async reload(sourceId: ExternalDataSource['id']): Promise<void> {
            await new ApiRequest().externalDataSource(sourceId).withAction('reload').create()
        },
        async update(
            sourceId: ExternalDataSource['id'],
            data: Partial<ExternalDataSource>
        ): Promise<ExternalDataSource> {
            return await new ApiRequest().externalDataSource(sourceId).update({ data })
        },
        async database_schema(
            source_type: ExternalDataSourceType,
            payload: Record<string, any>
        ): Promise<ExternalDataSourceSyncSchema[]> {
            return await new ApiRequest()
                .externalDataSources()
                .withAction('database_schema')
                .create({ data: { source_type, ...payload } })
        },
        async wizard(): Promise<Record<string, SourceConfig>> {
            return await new ApiRequest().externalDataSources().withAction('wizard').get()
        },
        async source_prefix(
            source_type: ExternalDataSourceType,
            prefix: string
        ): Promise<ExternalDataSourceSyncSchema[]> {
            return await new ApiRequest()
                .externalDataSources()
                .withAction('source_prefix')
                .create({ data: { source_type, prefix } })
        },
        async jobs(
            sourceId: ExternalDataSource['id'],
            before: string | null,
            after: string | null
        ): Promise<ExternalDataJob[]> {
            return await new ApiRequest()
                .externalDataSource(sourceId)
                .withAction('jobs')
                .withQueryString({ before, after })
                .get()
        },
        async updateRevenueAnalyticsConfig(
            sourceId: ExternalDataSource['id'],
            data: Partial<ExternalDataSourceRevenueAnalyticsConfig>
        ): Promise<ExternalDataSource> {
            return await new ApiRequest().externalDataSourceRevenueAnalyticsConfig(sourceId).update({ data })
        },
    },

    dataWarehouse: {
        async totalRowsStats(options?: ApiMethodOptions): Promise<DataWarehouseSourceRowCount> {
            return await new ApiRequest().dataWarehouse().withAction('total_rows_stats').get(options)
        },

        async recentActivity(
            options?: ApiMethodOptions & { limit?: number; offset?: number }
        ): Promise<PaginatedResponse<DataWarehouseActivityRecord>> {
            return await new ApiRequest()
                .dataWarehouse()
                .withAction('recent_activity')
                .withQueryString({ limit: options?.limit, offset: options?.offset })
                .get(options)
        },
    },

    externalDataSchemas: {
        async update(
            schemaId: ExternalDataSourceSchema['id'],
            data: Partial<ExternalDataSourceSchema>
        ): Promise<ExternalDataSourceSchema> {
            return await new ApiRequest().externalDataSourceSchema(schemaId).update({ data })
        },
        async reload(schemaId: ExternalDataSourceSchema['id']): Promise<void> {
            await new ApiRequest().externalDataSourceSchema(schemaId).withAction('reload').create()
        },
        async resync(schemaId: ExternalDataSourceSchema['id']): Promise<void> {
            await new ApiRequest().externalDataSourceSchema(schemaId).withAction('resync').create()
        },
        async incremental_fields(schemaId: ExternalDataSourceSchema['id']): Promise<SchemaIncrementalFieldsResponse> {
            return await new ApiRequest().externalDataSourceSchema(schemaId).withAction('incremental_fields').create()
        },
        async delete_data(schemaId: ExternalDataSourceSchema['id']): Promise<SchemaIncrementalFieldsResponse> {
            return await new ApiRequest().externalDataSourceSchema(schemaId).withAction('delete_data').delete()
        },
    },
    fixHogQLErrors: {
        async fix(query: string, error?: string): Promise<Record<string, any>> {
            return await new ApiRequest().fixHogQLErrors().create({ data: { query, error } })
        },
    },

    dataWarehouseViewLinks: {
        async list(): Promise<PaginatedResponse<DataWarehouseViewLink>> {
            return await new ApiRequest().dataWarehouseViewLinks().get()
        },
        async get(viewLinkId: DataWarehouseViewLink['id']): Promise<DataWarehouseViewLink> {
            return await new ApiRequest().dataWarehouseViewLink(viewLinkId).get()
        },
        async create(data: Partial<DataWarehouseViewLink>): Promise<DataWarehouseViewLink> {
            return await new ApiRequest().dataWarehouseViewLinks().create({ data })
        },
        async delete(viewId: DataWarehouseViewLink['id']): Promise<void> {
            await new ApiRequest().dataWarehouseViewLink(viewId).delete()
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().dataWarehouseViewLinks().assembleEndpointUrl()
        },
        async update(
            viewId: DataWarehouseViewLink['id'],
            data: Pick<
                DataWarehouseViewLink,
                | 'source_table_name'
                | 'source_table_key'
                | 'joining_table_name'
                | 'joining_table_key'
                | 'field_name'
                | 'configuration'
            >
        ): Promise<DataWarehouseViewLink> {
            return await new ApiRequest().dataWarehouseViewLink(viewId).update({ data })
        },
    },

    queryTabState: {
        async create(data: Partial<QueryTabState>): Promise<QueryTabState> {
            return await new ApiRequest().queryTabState().create({ data })
        },
        async get(id: QueryTabState['id']): Promise<QueryTabState> {
            return await new ApiRequest().queryTabStateDetail(id).get()
        },
        async update(id: QueryTabState['id'], data: Partial<QueryTabState>): Promise<QueryTabState> {
            return await new ApiRequest().queryTabStateDetail(id).update({ data })
        },
        async delete(id: QueryTabState['id']): Promise<void> {
            await new ApiRequest().queryTabStateDetail(id).delete()
        },
        async user(userId: UserType['uuid']): Promise<QueryTabState> {
            return await new ApiRequest().queryTabStateUser().withQueryString({ user_id: userId }).get()
        },
    },
    upstream: {
        async get(modelId: string): Promise<LineageGraph> {
            return await new ApiRequest().upstream(modelId).get()
        },
    },
    insightVariables: {
        async list(options?: ApiMethodOptions | undefined): Promise<PaginatedResponse<Variable>> {
            return await new ApiRequest().insightVariables().get(options)
        },
        async create(data: Partial<Variable>): Promise<Variable> {
            return await new ApiRequest().insightVariables().create({ data })
        },
        async update(variableId: string, data: Partial<Variable>): Promise<Variable> {
            return await new ApiRequest().insightVariable(variableId).update({ data })
        },
        async delete(variableId: string): Promise<void> {
            await new ApiRequest().insightVariable(variableId).delete()
        },
    },

    subscriptions: {
        async get(subscriptionId: SubscriptionType['id']): Promise<SubscriptionType> {
            return await new ApiRequest().subscription(subscriptionId).get()
        },
        async create(data: Partial<SubscriptionType>): Promise<SubscriptionType> {
            return await new ApiRequest().subscriptions().create({ data })
        },
        async update(
            subscriptionId: SubscriptionType['id'],
            data: Partial<SubscriptionType>
        ): Promise<SubscriptionType> {
            return await new ApiRequest().subscription(subscriptionId).update({ data })
        },
        async list({
            insightId,
            dashboardId,
        }: {
            insightId?: number
            dashboardId?: number
        }): Promise<PaginatedResponse<SubscriptionType>> {
            return await new ApiRequest()
                .subscriptions()
                .withQueryString(insightId ? `insight=${insightId}` : dashboardId ? `dashboard=${dashboardId}` : '')
                .get()
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().subscriptions().assembleEndpointUrl()
        },
    },

    integrations: {
        async get(id: IntegrationType['id']): Promise<IntegrationType> {
            return await new ApiRequest().integration(id).get()
        },
        async create(data: Partial<IntegrationType> | FormData): Promise<IntegrationType> {
            return await new ApiRequest().integrations().create({ data })
        },
        async delete(integrationId: IntegrationType['id']): Promise<IntegrationType> {
            return await new ApiRequest().integration(integrationId).delete()
        },
        async list(): Promise<PaginatedResponse<IntegrationType>> {
            return await new ApiRequest().integrations().get()
        },
        authorizeUrl(params: { kind: string; next?: string }): string {
            return new ApiRequest().integrations().withAction('authorize').withQueryString(params).assembleFullUrl(true)
        },
        async slackChannels(
            id: IntegrationType['id'],
            forceRefresh: boolean
        ): Promise<{ channels: SlackChannelType[]; lastRefreshedAt: string }> {
            return await new ApiRequest().integrationSlackChannels(id, forceRefresh).get()
        },
        async slackChannelsById(
            id: IntegrationType['id'],
            channelId: string
        ): Promise<{ channels: SlackChannelType[] }> {
            return await new ApiRequest().integrationSlackChannelsById(id, channelId).get()
        },
        async twilioPhoneNumbers(
            id: IntegrationType['id'],
            forceRefresh: boolean
        ): Promise<{ phone_numbers: TwilioPhoneNumberType[]; lastRefreshedAt: string }> {
            return await new ApiRequest().integrationTwilioPhoneNumbers(id, forceRefresh).get()
        },
        async linearTeams(id: IntegrationType['id']): Promise<{ teams: LinearTeamType[] }> {
            return await new ApiRequest().integrationLinearTeams(id).get()
        },
        async githubRepositories(id: IntegrationType['id']): Promise<{ repositories: string[] }> {
            return await new ApiRequest().integrationGitHubRepositories(id).get()
        },
        async googleAdsAccounts(
            id: IntegrationType['id']
        ): Promise<{ accessibleAccounts: { id: string; name: string; level: string; parent_id: string }[] }> {
            return await new ApiRequest().integrationGoogleAdsAccounts(id).get()
        },
        async googleAdsConversionActions(
            id: IntegrationType['id'],
            params: { customerId: string; parentId: string }
        ): Promise<{ conversionActions: GoogleAdsConversionActionType[] }> {
            return await new ApiRequest().integrationGoogleAdsConversionActions(id, params).get()
        },
        async linkedInAdsAccounts(id: IntegrationType['id']): Promise<{ adAccounts: LinkedInAdsAccountType[] }> {
            return await new ApiRequest().integrationLinkedInAdsAccounts(id).get()
        },
        async linkedInAdsConversionRules(
            id: IntegrationType['id'],
            accountId: string
        ): Promise<{ conversionRules: LinkedInAdsConversionRuleType[] }> {
            return await new ApiRequest().integrationLinkedInAdsConversionRules(id, accountId).get()
        },
        async clickUpSpaces(
            id: IntegrationType['id'],
            workspaceId: string,
            teamId?: TeamType['id']
        ): Promise<{ spaces: { id: string; name: string }[] }> {
            return await new ApiRequest().integrationClickUpSpaces(id, workspaceId, teamId).get()
        },
        async clickUpLists(
            id: IntegrationType['id'],
            spaceId: string,
            teamId?: TeamType['id']
        ): Promise<{ lists: { id: string; name: string }[] }> {
            return await new ApiRequest().integrationClickUpLists(id, spaceId, teamId).get()
        },
        async clickUpWorkspaces(
            id: IntegrationType['id'],
            teamId?: TeamType['id']
        ): Promise<{ workspaces: { id: string; name: string }[] }> {
            return await new ApiRequest().integrationClickUpWorkspaces(id, teamId).get()
        },
        async verifyEmail(id: IntegrationType['id']): Promise<EmailSenderDomainStatus> {
            return await new ApiRequest().integrationEmailVerify(id).create()
        },
    },

    media: {
        async upload(data: FormData): Promise<MediaUploadResponse> {
            return await new ApiRequest().media().create({ data })
        },
    },

    queryStatus: {
        async get(queryId: string, showProgress: boolean): Promise<QueryStatusResponse> {
            return await new ApiRequest().queryStatus(queryId, showProgress).get()
        },
    },

    queryLog: {
        async get(queryId: string): Promise<HogQLQueryResponse> {
            return await new ApiRequest().queryLog(queryId).get()
        },
    },

    personalApiKeys: {
        async list(): Promise<PersonalAPIKeyType[]> {
            return await new ApiRequest().personalApiKeys().get()
        },
        async create(data: Partial<PersonalAPIKeyType>): Promise<PersonalAPIKeyType> {
            return await new ApiRequest().personalApiKeys().create({ data })
        },
        async update(id: PersonalAPIKeyType['id'], data: Partial<PersonalAPIKeyType>): Promise<PersonalAPIKeyType> {
            return await new ApiRequest().personalApiKey(id).update({ data })
        },
        async delete(id: PersonalAPIKeyType['id']): Promise<void> {
            await new ApiRequest().personalApiKey(id).delete()
        },
        async roll(id: PersonalAPIKeyType['id']): Promise<PersonalAPIKeyType> {
            return await new ApiRequest().personalApiKey(id).withAction('roll').create()
        },
    },

    alerts: {
        async get(alertId: AlertType['id']): Promise<AlertType> {
            return await new ApiRequest().alert(alertId).get()
        },
        async create(data: Partial<AlertTypeWrite>): Promise<AlertType> {
            return await new ApiRequest().alerts().create({ data })
        },
        async update(alertId: AlertType['id'], data: Partial<AlertTypeWrite>): Promise<AlertType> {
            return await new ApiRequest().alert(alertId).update({ data })
        },
        async list(insightId?: InsightModel['id']): Promise<PaginatedResponse<AlertType>> {
            return await new ApiRequest().alerts(undefined, insightId).get()
        },
        async delete(alertId: AlertType['id']): Promise<void> {
            return await new ApiRequest().alert(alertId).delete()
        },
    },

    dataColorThemes: {
        async list(): Promise<DataColorThemeModel[]> {
            return await new ApiRequest().dataColorThemes().get()
        },
        async create(data: Partial<DataColorThemeModel>): Promise<DataColorThemeModel> {
            return await new ApiRequest().dataColorThemes().create({ data })
        },
        async update(id: DataColorThemeModel['id'], data: Partial<DataColorThemeModel>): Promise<DataColorThemeModel> {
            return await new ApiRequest().dataColorTheme(id).update({ data })
        },
    },

    productIntents: {
        async update(data: ProductIntentProperties): Promise<TeamType> {
            return await new ApiRequest().addProductIntent().update({ data })
        },
    },

    coreMemory: {
        async list(): Promise<PaginatedResponse<CoreMemory>> {
            return await new ApiRequest().coreMemory().get()
        },
        async create(coreMemory: Pick<CoreMemory, 'text'>): Promise<CoreMemory> {
            return await new ApiRequest().coreMemory().create({
                data: coreMemory,
            })
        },
        async update(coreMemoryId: CoreMemory['id'], coreMemory: Pick<CoreMemory, 'text'>): Promise<CoreMemory> {
            return await new ApiRequest().coreMemoryDetail(coreMemoryId).update({ data: coreMemory })
        },
    },
    wizard: {
        async authenticateWizard(data: { hash: string; projectId: number }): Promise<{ success: boolean }> {
            return await new ApiRequest().authenticateWizard().create({ data })
        },
    },
    messaging: {
        async getTemplates(): Promise<PaginatedResponse<MessageTemplate>> {
            return await new ApiRequest().messagingTemplates().get()
        },
        async getTemplate(templateId: MessageTemplate['id']): Promise<MessageTemplate> {
            return await new ApiRequest().messagingTemplate(templateId).get()
        },
        async createTemplate(data: Partial<MessageTemplate>): Promise<MessageTemplate> {
            return await new ApiRequest().messagingTemplates().create({ data })
        },
        async updateTemplate(
            templateId: MessageTemplate['id'],
            data: Partial<MessageTemplate>
        ): Promise<MessageTemplate> {
            return await new ApiRequest().messagingTemplate(templateId).update({ data })
        },

        // Messaging Categories
        async getCategories(params?: { category_type?: string }): Promise<PaginatedResponse<any>> {
            return await new ApiRequest()
                .messagingCategories()
                .withQueryString(toParams(params || {}))
                .get()
        },
        async getCategory(categoryId: string): Promise<any> {
            return await new ApiRequest().messagingCategory(categoryId).get()
        },
        async createCategory(data: any): Promise<any> {
            return await new ApiRequest().messagingCategories().create({ data })
        },
        async updateCategory(categoryId: string, data: any): Promise<any> {
            return await new ApiRequest().messagingCategory(categoryId).update({ data })
        },
        async deleteCategory(categoryId: string): Promise<void> {
            return await new ApiRequest().messagingCategory(categoryId).delete()
        },
        async generateMessagingPreferencesLink(recipient?: string): Promise<string | null> {
            const response = await new ApiRequest().messagingPreferencesLink().create({
                data: {
                    recipient,
                },
            })
            return response.preferences_url || null
        },
        async getMessageOptOuts(categoryKey?: string): Promise<OptOutEntry[]> {
            return await new ApiRequest()
                .messagingPreferencesOptOuts()
                .withQueryString({
                    category_key: categoryKey,
                })
                .get()
        },
    },
    oauthApplication: {
        async getPublicMetadata(clientId: string): Promise<OAuthApplicationPublicMetadata> {
            return await new ApiRequest().oauthApplicationPublicMetadata(clientId).get()
        },
    },
    hogFlows: {
        async getHogFlows(): Promise<PaginatedResponse<HogFlow>> {
            return await new ApiRequest().hogFlows().get()
        },
        async getHogFlow(hogFlowId: HogFlow['id']): Promise<HogFlow> {
            return await new ApiRequest().hogFlow(hogFlowId).get()
        },
        async createHogFlow(data: Partial<HogFlow>): Promise<HogFlow> {
            return await new ApiRequest().hogFlows().create({ data })
        },
        async updateHogFlow(hogFlowId: HogFlow['id'], data: Partial<HogFlow>): Promise<HogFlow> {
            return await new ApiRequest().hogFlow(hogFlowId).update({ data })
        },
        async deleteHogFlow(hogFlowId: HogFlow['id']): Promise<void> {
            return await new ApiRequest().hogFlow(hogFlowId).delete()
        },
        async createTestInvocation(
            hogFlowId: HogFlow['id'],
            data: {
                configuration: Record<string, any>
                mock_async_functions: boolean
                globals?: any
                clickhouse_event?: any
                invocation_id?: string
                current_action_id?: string
            }
        ): Promise<HogflowTestResult> {
            return await new ApiRequest().hogFlow(hogFlowId).withAction('invocations').create({ data })
        },
    },

    queryURL: (): string => {
        return new ApiRequest().query().assembleFullUrl(true)
    },

    async query<T extends Record<string, any> = QuerySchema>(
        query: T,
        queryOptions?: {
            requestOptions?: ApiMethodOptions
            clientQueryId?: string
            refresh?: RefreshType
            filtersOverride?: DashboardFilter | null
            variablesOverride?: Record<string, HogQLVariable> | null
        }
    ): Promise<
        T extends { [response: string]: any }
            ? T['response'] extends infer P | undefined
                ? P
                : T['response']
            : Record<string, any>
    > {
        return await new ApiRequest().query().create({
            ...queryOptions?.requestOptions,
            data: {
                query,
                client_query_id: queryOptions?.clientQueryId,
                refresh: queryOptions?.refresh,
                filters_override: queryOptions?.filtersOverride,
                variables_override: queryOptions?.variablesOverride,
            },
        })
    },

    async queryHogQL<T = any[]>(
        query: HogQLQueryString,
        queryOptions?: {
            requestOptions?: ApiMethodOptions
            clientQueryId?: string
            refresh?: RefreshType
            filtersOverride?: DashboardFilter | null
            variablesOverride?: Record<string, HogQLVariable> | null
            queryParams?: Omit<HogQLQuery, 'kind' | 'query'>
        }
    ): Promise<HogQLQueryResponse<T>> {
        const hogQLQuery: HogQLQuery = setLatestVersionsOnQuery({
            ...queryOptions?.queryParams,
            kind: NodeKind.HogQLQuery,
            query,
        })
        return await new ApiRequest().query().create({
            ...queryOptions?.requestOptions,
            data: {
                query: hogQLQuery,
                client_query_id: queryOptions?.clientQueryId,
                refresh: queryOptions?.refresh,
                filters_override: queryOptions?.filtersOverride,
                variables_override: queryOptions?.variablesOverride,
            },
        })
    },

    schema: {
        async queryUpgrade(data: { query: Node }): Promise<{ query: Node }> {
            return await new ApiRequest().queryUpgrade().create({ data })
        },
    },

    conversations: {
        async stream(
            data: {
                /** The user message. Null content means we're resuming streaming or continuing previous generation. */
                content: string | null
                contextual_tools?: Record<string, any>
                ui_context?: MaxUIContext
                billing_context?: MaxBillingContext
                conversation?: string | null
                trace_id: string
            },
            options?: ApiMethodOptions
        ): Promise<Response> {
            return api.createResponse(new ApiRequest().conversations().assembleFullUrl(), data, options)
        },

        cancel(conversationId: string): Promise<void> {
            return new ApiRequest().conversation(conversationId).withAction('cancel').update()
        },

        list(): Promise<PaginatedResponse<ConversationDetail>> {
            return new ApiRequest().conversations().get()
        },

        get(conversationId: string): Promise<ConversationDetail> {
            return new ApiRequest().conversation(conversationId).get()
        },
    },

    datasets: {
        list({
            ids,
            ...params
        }: {
            search?: string
            order_by?: string
            offset?: number
            limit?: number
            ids?: string[]
        }): Promise<CountedPaginatedResponse<Dataset>> {
            return new ApiRequest()
                .datasets()
                .withQueryString({
                    ...params,
                    id__in: ids?.join(','),
                })
                .get()
        },

        get(datasetId: string): Promise<Dataset> {
            return new ApiRequest().dataset(datasetId).get()
        },

        async create(data: Omit<Partial<Dataset>, 'created_by' | 'team'>): Promise<Dataset> {
            return await new ApiRequest().datasets().create({ data })
        },

        async update(datasetId: string, data: Omit<Partial<Dataset>, 'created_by' | 'team'>): Promise<Dataset> {
            return await new ApiRequest().dataset(datasetId).update({ data })
        },
    },

    evaluationRuns: {
        async create(data: { evaluation_id: string; target_event_id: string }): Promise<{
            workflow_id: string
            status: string
            evaluation: { id: string; name: string }
            target_event_id: string
        }> {
            return await new ApiRequest().evaluationRuns().create({ data })
        },
    },

    datasetItems: {
        list(data: {
            dataset: string
            limit?: number
            offset?: number
        }): Promise<CountedPaginatedResponse<DatasetItem>> {
            return new ApiRequest().datasetItems().withQueryString(data).get()
        },

        async create(data: Partial<DatasetItem>): Promise<DatasetItem> {
            return await new ApiRequest().datasetItems().create({ data })
        },

        async update(datasetItemId: string, data: Partial<DatasetItem>): Promise<DatasetItem> {
            return await new ApiRequest().datasetItem(datasetItemId).update({ data })
        },
    },

    /** Fetch data from specified URL. The result already is JSON-parsed. */
    async get<T = any>(url: string, options?: ApiMethodOptions): Promise<T> {
        const res = await api.getResponse(url, options)
        return await getJSONOrNull(res)
    },

    async getResponse(url: string, options?: ApiMethodOptions): Promise<Response> {
        url = prepareUrl(url)
        ensureProjectIdNotInvalid(url)

        // Add JWT token to Authorization header if available
        const exporterContext = getCurrentExporterData()
        const authHeaders: Record<string, string> = {}
        if (exporterContext?.shareToken) {
            authHeaders['Authorization'] = `Bearer ${exporterContext.shareToken}`
        }

        return await handleFetch(url, 'GET', () => {
            return fetch(url, {
                signal: options?.signal,
                headers: {
                    ...objectClean(options?.headers ?? {}),
                    ...(getSessionId() ? { 'X-POSTHOG-SESSION-ID': getSessionId() } : {}),
                    ...(getDistinctId() ? { 'X-POSTHOG-DISTINCT-ID': getDistinctId() } : {}),
                    ...authHeaders,
                },
            })
        })
    },

    async _update<T = any, P = any>(
        method: 'PATCH' | 'PUT',
        url: string,
        data: P,
        options?: ApiMethodOptions
    ): Promise<T> {
        url = prepareUrl(url)
        ensureProjectIdNotInvalid(url)
        const isFormData = data instanceof FormData

        const response = await handleFetch(url, method, async () => {
            return await fetch(url, {
                method: method,
                headers: {
                    ...objectClean(options?.headers ?? {}),
                    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                    'X-CSRFToken': getCookie(CSRF_COOKIE_NAME) || '',
                    ...(getSessionId() ? { 'X-POSTHOG-SESSION-ID': getSessionId() } : {}),
                },
                body: isFormData ? data : JSON.stringify(data),
                signal: options?.signal,
            })
        })

        return await getJSONOrNull(response)
    },

    async update<T = any, P = any>(url: string, data: P, options?: ApiMethodOptions): Promise<T> {
        return api._update('PATCH', url, data, options)
    },

    async put<T = any, P = any>(url: string, data: P, options?: ApiMethodOptions): Promise<T> {
        return api._update('PUT', url, data, options)
    },

    async create<T = any, P = any>(url: string, data?: P, options?: ApiMethodOptions): Promise<T> {
        const res = await api.createResponse(url, data, options)
        return await getJSONOrNull(res)
    },

    async createResponse(url: string, data?: any, options?: ApiMethodOptions): Promise<Response> {
        url = prepareUrl(url)
        ensureProjectIdNotInvalid(url)
        const isFormData = data instanceof FormData

        return await handleFetch(url, 'POST', () =>
            fetch(url, {
                method: 'POST',
                headers: {
                    ...objectClean(options?.headers ?? {}),
                    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                    'X-CSRFToken': getCookie(CSRF_COOKIE_NAME) || '',
                    ...(getSessionId() ? { 'X-POSTHOG-SESSION-ID': getSessionId() } : {}),
                },
                body: data ? (isFormData ? data : JSON.stringify(data)) : undefined,
                signal: options?.signal,
            })
        )
    },

    async delete(url: string): Promise<any> {
        url = prepareUrl(url)
        ensureProjectIdNotInvalid(url)
        return await handleFetch(url, 'DELETE', () =>
            fetch(url, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': getCookie(CSRF_COOKIE_NAME) || '',
                    ...(getSessionId() ? { 'X-POSTHOG-SESSION-ID': getSessionId() } : {}),
                },
            })
        )
    },

    /** Stream server-sent events over an EventSource. */
    async stream(
        url: string,
        {
            method = 'GET',
            data,
            onMessage,
            onError,
            headers,
            signal,
        }:
            | {
                  method?: 'GET'
                  /** GET requests cannot contain a body, use URL params instead. */
                  data?: never
                  onMessage: (data: EventSourceMessage) => void
                  onError: (error: any) => void
                  headers?: Record<string, string>
                  signal?: AbortSignal
              }
            | {
                  method: 'POST'
                  /** Any JSON-serializable object. */
                  data: any
                  onMessage: (data: EventSourceMessage) => void
                  onError: (error: any) => void
                  headers?: Record<string, string>
                  signal?: AbortSignal
              }
    ): Promise<void> {
        await fetchEventSource(url, {
            method,
            headers: {
                ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
                'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                ...(getSessionId() ? { 'X-POSTHOG-SESSION-ID': getSessionId() } : {}),
                ...objectClean(headers ?? {}),
            },
            body: data !== undefined ? JSON.stringify(data) : undefined,
            signal,
            onmessage: onMessage,
            onerror: onError,
            // By default fetch-event-source stops connection when document is no longer focused, but that is not how
            // EventSource works normally, hence reverting (https://github.com/Azure/fetch-event-source/issues/36)
            openWhenHidden: true,
        })
    },

    async loadPaginatedResults<T extends Record<string, any>>(
        url: string | null,
        maxIterations: number = PAGINATION_DEFAULT_MAX_PAGES
    ): Promise<T[]> {
        let results: T[] = []
        for (let i = 0; i <= maxIterations; ++i) {
            if (!url) {
                break
            }

            const { results: partialResults, next } = await api.get(url)
            results = results.concat(partialResults)
            url = next
        }
        return results
    },

    sessionSummaries: {
        async create(data: { session_ids: string[]; focus_area?: string }): Promise<SessionSummaryResponse> {
            return await new ApiRequest().sessionSummary().withAction('create_session_summaries').create({ data })
        },
    },

    dataWarehouseManagedViewsets: {
        async toggle(kind: DataWarehouseManagedViewsetKind, enabled: boolean): Promise<void> {
            return await new ApiRequest().dataWarehouseManagedViewset(kind).put({ data: { enabled } })
        },
        async getViews(
            kind: DataWarehouseManagedViewsetKind
        ): Promise<{ views: DataWarehouseManagedViewsetSavedQuery[]; count: number }> {
            return await new ApiRequest().dataWarehouseManagedViewset(kind).get()
        },
    },
}

async function handleFetch(url: string, method: string, fetcher: () => Promise<Response>): Promise<Response> {
    const startTime = new Date().getTime()

    let response
    let error
    try {
        response = await fetcher()
    } catch (e) {
        error = e
    }

    apiStatusLogic.findMounted()?.actions.onApiResponse(response?.clone(), error)

    if (error || !response) {
        if (error && (error as any).name === 'AbortError') {
            throw error
        }
        throw new ApiError(error as any, response?.status)
    }

    if (!response.ok) {
        const duration = new Date().getTime() - startTime
        const pathname = new URL(url, location.origin).pathname
        // when used inside the posthog toolbar, `posthog.capture` isn't loaded
        // check if the function is available before calling it.
        if (posthog.capture) {
            posthog.capture('client_request_failure', { pathname, method, duration, status: response.status })
        }

        const data = await getJSONOrNull(response)

        if (response.status >= 400 && data && typeof data.error === 'string') {
            throw new ApiError(data.error, response.status, response.headers, data)
        }

        throw new ApiError('Non-OK response', response.status, response.headers, data)
    }

    return response
}

export default api
