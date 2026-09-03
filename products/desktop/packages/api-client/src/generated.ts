export namespace Schemas {
    // <Schemas>
    export type AIEventType =
        | "$ai_generation"
        | "$ai_embedding"
        | "$ai_span"
        | "$ai_trace"
        | "$ai_metric"
        | "$ai_feedback"
        | "$ai_evaluation"
        | "$ai_tag"
        | "$ai_trace_summary"
        | "$ai_generation_summary"
        | "$ai_trace_clusters"
        | "$ai_generation_clusters";
    export type AccessControlFilterWarning = {
        /**
         * Human-readable warning shown to the user
         */
        message: string;
        /**
         * Resource types the user has access restrictions on, referenced by the query, e.g. ["insight", "dashboard"]
         */
        resources: Array<string>;
        type?: string | undefined;
    };
    export type PropertyOperator =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "starts_with"
        | "not_starts_with"
        | "ends_with"
        | "not_ends_with"
        | "regex"
        | "not_regex"
        | "gt"
        | "gte"
        | "lt"
        | "lte"
        | "is_set"
        | "is_not_set"
        | "is_date_exact"
        | "is_date_before"
        | "is_date_after"
        | "between"
        | "not_between"
        | "min"
        | "max"
        | "in"
        | "not_in"
        | "is_cleaned_path_exact"
        | "flag_evaluates_to"
        | "semver_eq"
        | "semver_neq"
        | "semver_gt"
        | "semver_gte"
        | "semver_lt"
        | "semver_lte"
        | "semver_tilde"
        | "semver_caret"
        | "semver_wildcard"
        | "icontains_multi"
        | "not_icontains_multi";
    export type AccountCustomPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type BounceRatePageViewMode =
        | "count_pageviews"
        | "uniq_urls"
        | "uniq_page_screen_autocaptures";
    export type FilterLogicalOperator = "AND" | "OR";
    export type CustomChannelField =
        | "utm_source"
        | "utm_medium"
        | "utm_campaign"
        | "referring_domain"
        | "url"
        | "pathname"
        | "hostname";
    export type CustomChannelOperator =
        | "exact"
        | "is_not"
        | "is_set"
        | "is_not_set"
        | "icontains"
        | "not_icontains"
        | "regex"
        | "not_regex";
    export type CustomChannelCondition = {
        id: string;
        key: CustomChannelField;
        op: CustomChannelOperator;
        value?: (string | Array<string> | null) | undefined;
    };
    export type CustomChannelRule = {
        channel_type: string;
        combiner: FilterLogicalOperator;
        id: string;
        items: Array<CustomChannelCondition>;
    };
    export type DataWarehouseEventsModifier = {
        distinct_id_field: string;
        id_field: string;
        table_name: string;
        timestamp_field: string;
    };
    export type InCohortVia =
        | "auto"
        | "leftjoin"
        | "subquery"
        | "leftjoin_conjoined";
    export type InlineCohortCalculation = "off" | "auto" | "always";
    export type MaterializationMode =
        | "auto"
        | "legacy_null_as_string"
        | "legacy_null_as_null"
        | "disabled";
    export type MaterializedColumnsOptimizationMode = "disabled" | "optimized";
    export type ParserMode =
        | "cpp_only"
        | "cpp_with_rust_shadow"
        | "cpp_with_rust_py_shadow"
        | "rust_with_cpp_shadow"
        | "rust_only"
        | "rust_py_only"
        | "rust_py_with_cpp_shadow";
    export type PersonsArgMaxVersion = "auto" | "v1" | "v2";
    export type PersonsJoinMode = "inner" | "left";
    export type PersonsOnEventsMode =
        | "disabled"
        | "person_id_no_override_properties_on_events"
        | "person_id_override_properties_on_events"
        | "person_id_override_properties_joined";
    export type PropertyGroupsMode = "enabled" | "disabled" | "optimized";
    export type SessionTableVersion = "auto" | "v1" | "v2" | "v3";
    export type SessionsV2JoinMode = "string" | "uuid";
    export type HogQLQueryModifiers = Partial<{
        bounceRateDurationSeconds: number | null;
        bounceRatePageViewMode: BounceRatePageViewMode | null;
        convertToProjectTimezone: boolean | null;
        customChannelTypeRules: Array<CustomChannelRule> | null;
        dataWarehouseEventsModifiers: Array<DataWarehouseEventsModifier> | null;
        debug: boolean | null;
        forceClickhouseDataSkippingIndexes: Array<string> | null;
        formatCsvAllowDoubleQuotes: boolean | null;
        inCohortVia: InCohortVia | null;
        inlineCohortCalculation: InlineCohortCalculation | null;
        materializationMode: MaterializationMode | null;
        materializedColumnsOptimizationMode: MaterializedColumnsOptimizationMode | null;
        mergeFederatedAggregateJoins: boolean | null;
        optimizeJoinedFilters: boolean | null;
        optimizeProjections: boolean | null;
        parserMode: ParserMode | null;
        personsArgMaxVersion: PersonsArgMaxVersion | null;
        personsJoinMode: PersonsJoinMode | null;
        personsOnEventsMode: PersonsOnEventsMode | null;
        propertyGroupsMode: PropertyGroupsMode | null;
        pushDownPredicates: boolean | null;
        s3TableUseInvalidColumns: boolean | null;
        sessionIdPushdown: boolean | null;
        sessionPropertyPreAggregation: boolean | null;
        sessionTableVersion: SessionTableVersion | null;
        sessionsV2JoinMode: SessionsV2JoinMode | null;
        timings: boolean | null;
        typeAwareCastSimplification: boolean | null;
        useMaterializedViews: boolean | null;
        usePreaggregatedIntermediateResults: boolean | null;
        usePreaggregatedTableTransforms: boolean | null;
        useWebAnalyticsPreAggregatedTables: boolean | null;
        webAnalyticsFirstPageviewFilters: boolean | null;
    }>;
    export type ClickhouseQueryProgress = {
        active_cpu_time: number;
        bytes_read: number;
        estimated_rows_total: number;
        rows_read: number;
        time_elapsed: number;
    };
    export type QueryStatus = {
        complete?: (boolean | null) | undefined;
        dashboard_id?: (number | null) | undefined;
        end_time?: (string | null) | undefined;
        error?: (boolean | null) | undefined;
        error_code?: (string | null) | undefined;
        error_message?: (string | null) | undefined;
        expiration_time?: (string | null) | undefined;
        id: string;
        insight_id?: (number | null) | undefined;
        labels?: (Array<string> | null) | undefined;
        pickup_time?: (string | null) | undefined;
        query_async?: boolean | undefined;
        query_progress?: (ClickhouseQueryProgress | null) | undefined;
        results?: unknown | undefined;
        start_time?: (string | null) | undefined;
        task_id?: (string | null) | undefined;
        team_id: number;
    };
    export type ResolvedDateRangeResponse = {
        date_from: string;
        date_to: string;
    };
    export type QueryTiming = {
        /**
         * Key. Shortened to 'k' to save on data.
         */
        k: string;
        /**
         * Time in seconds. Shortened to 't' to save on data.
         */
        t: number;
    };
    export type DataWarehouseSourceUsage = {
        /**
         * ExternalDataSource id
         */
        id: string;
        source_type?: (string | null) | undefined;
        /**
         * Warehouse table name that was referenced
         */
        table_name: string;
    };
    export type DataWarehouseSyncWarning = {
        /**
         * Human-readable warning shown to the user
         */
        message: string;
        /**
         * Name of the ExternalDataSchema responsible for syncing the table
         */
        schema_name: string;
        source_id?: (string | null) | undefined;
        /**
         * Source type, e.g. "Stripe", "Hubspot"
         */
        source_type: string;
        /**
         * Sync status that triggered the warning, e.g. "Failed", "Paused", "BillingLimitReached"
         */
        status: string;
        /**
         * Name of the warehouse table the warning refers to
         */
        table_name: string;
        type?: string | undefined;
    };
    export type AccountsQueryResponse = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        kind?: string | undefined;
        limit: number;
        metricsResults?: (Array<number | null> | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type QueryLogTags = Partial<{
        name: string | null;
        productKey: string | null;
        scene: string | null;
    }>;
    export type AccountsQuery = Partial<{
        allRolesUnassigned: boolean | null;
        assignedToUserIds: Array<number> | null;
        filterExpression: string | null;
        includeIgnored: boolean | null;
        kind: string;
        limit: number | null;
        metrics: Array<string> | null;
        modifiers: HogQLQueryModifiers | null;
        offset: number | null;
        orderBy: Array<string> | null;
        response: AccountsQueryResponse | null;
        search: string | null;
        select: Array<string> | null;
        tagNames: Array<string> | null;
        tags: QueryLogTags | null;
        version: number | null;
    }>;
    export type AccountsTableAccountField =
        | "name"
        | "external_id"
        | "created_at"
        | "updated_at"
        | "churned_at"
        | "ignored_at"
        | "stripe_customer_id"
        | "hubspot_deal_id"
        | "billing_id"
        | "sfdc_id"
        | "zendesk_id";
    export type AccountsTableAccountFieldColumn = {
        field: AccountsTableAccountField;
        kind?: string | undefined;
    };
    export type AccountsTableAccountFieldOperator =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "is_set"
        | "is_not_set"
        | "is_date_exact"
        | "is_date_before"
        | "is_date_after";
    export type AccountsTableAccountFieldFilter = {
        field: AccountsTableAccountField;
        kind?: string | undefined;
        operator: AccountsTableAccountFieldOperator;
        values?: (Array<string> | null) | undefined;
    };
    export type AccountsTableAccountIdFilter = {
        accountId: string;
        kind?: string | undefined;
    };
    export type AccountsTableAggregation =
        | "sum"
        | "avg"
        | "min"
        | "max"
        | "median";
    export type AccountsTableCustomPropertyColumn = {
        /**
         * Team-scoped custom property definition to return for each account.
         */
        definitionId: string;
        kind?: string | undefined;
    };
    export type AccountsTableAggregateMetric = {
        aggregation: AccountsTableAggregation;
        column: AccountsTableCustomPropertyColumn;
        kind?: string | undefined;
        scale?: (number | null) | undefined;
    };
    export type AccountsTableAssignedFilter = Partial<{ kind: string }>;
    export type AccountsTableAssignedToFilter = {
        kind?: string | undefined;
        /**
         * Match accounts where any listed user actively holds any relationship.
         */
        userIds: Array<number>;
    };
    export type AccountsTableCountMetric = Partial<{ kind: string }>;
    export type AccountsTableThresholdOperator =
        | "gt"
        | "gte"
        | "lt"
        | "lte"
        | "exact"
        | "is_not";
    export type AccountsTableCountThresholdMetric = {
        column: AccountsTableCustomPropertyColumn;
        kind?: string | undefined;
        operator: AccountsTableThresholdOperator;
        value: number;
    };
    export type AccountsTableCustomPropertyOperator =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "regex"
        | "not_regex"
        | "gt"
        | "gte"
        | "lt"
        | "lte"
        | "is_set"
        | "is_not_set"
        | "is_date_exact"
        | "is_date_before"
        | "is_date_after";
    export type AccountsTableCustomPropertyFilter = {
        definitionId: string;
        kind?: string | undefined;
        operator: AccountsTableCustomPropertyOperator;
        values?: (Array<string | number | boolean> | null) | undefined;
    };
    export type WindowDays = 7 | 14 | 30 | 90;
    export type AccountsTableCustomPropertyHistoryColumn = {
        /**
         * Team-scoped numeric custom property definition whose write history should be returned.
         */
        definitionId: string;
        kind?: string | undefined;
        /**
         * Number of days of history to return. The current value is included even when it is older.
         */
        windowDays: WindowDays;
    };
    export type AccountsTableCustomPropertyHistoryPoint = {
        timestamp: string;
        value: number;
    };
    export type AccountsTableNoteCountColumn = Partial<{ kind: string }>;
    export type AccountsTableTagsColumn = Partial<{ kind: string }>;
    export type AccountsTableRelationshipColumn = {
        /**
         * Team-scoped relationship definition to return for each account.
         */
        definitionId: string;
        kind?: string | undefined;
    };
    export type AccountsTableSearchFilter = {
        kind?: string | undefined;
        query: string;
    };
    export type AccountsTableTagsFilter = {
        kind?: string | undefined;
        /**
         * Match accounts carrying any of these tag names.
         */
        tagNames: Array<string>;
    };
    export type AccountsTableUnassignedFilter = Partial<{ kind: string }>;
    export type AccountsTableRelationshipOperator =
        | "exact"
        | "is_not"
        | "is_set"
        | "is_not_set";
    export type AccountsTableRelationshipFilter = {
        definitionId: string;
        kind?: string | undefined;
        operator: AccountsTableRelationshipOperator;
        userIds?: (Array<number> | null) | undefined;
    };
    export type AccountsTableRow = {
        /**
         * Requested direct Account fields, keyed by their typed field reference.
         */
        accountFields: Record<string, string | null>;
        /**
         * Current values keyed by requested custom property definition ID.
         */
        customProperties: Record<string, string | number | boolean | null>;
        /**
         * Numeric write history keyed by requested custom property definition ID.
         */
        customPropertyHistory: Record<
            string,
            Array<AccountsTableCustomPropertyHistoryPoint>
        >;
        externalId?: (string | null) | undefined;
        id: string;
        logoDomain?: (string | null) | undefined;
        name: string;
        noteCount?: (number | null) | undefined;
        /**
         * Active assignee user IDs keyed by requested relationship definition ID.
         */
        relationships: Record<string, Array<number>>;
        tags?: (Array<string> | null) | undefined;
    };
    export type AccountsTableQueryResponse = {
        error?: (string | null) | undefined;
        hasMore: boolean;
        hogql?: (string | null) | undefined;
        kind?: string | undefined;
        limit: number;
        metricsResults?: (Array<number | null> | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<AccountsTableRow>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type AccountsTableSortDirection = "asc" | "desc";
    export type AccountsTableSort = {
        /**
         * A typed column that supports server-side sorting.
         */
        column:
            | AccountsTableAccountFieldColumn
            | AccountsTableTagsColumn
            | AccountsTableNoteCountColumn
            | AccountsTableRelationshipColumn
            | AccountsTableCustomPropertyColumn;
        direction: AccountsTableSortDirection;
    };
    export type AccountsTableQuery = {
        /**
         * Columns to load for each account. Account identity fields are always returned.
         */
        columns: Array<
            | AccountsTableAccountFieldColumn
            | AccountsTableTagsColumn
            | AccountsTableNoteCountColumn
            | AccountsTableRelationshipColumn
            | AccountsTableCustomPropertyColumn
            | AccountsTableCustomPropertyHistoryColumn
        >;
        filters?:
            | (Array<
                  | AccountsTableSearchFilter
                  | AccountsTableTagsFilter
                  | AccountsTableAssignedToFilter
                  | AccountsTableAssignedFilter
                  | AccountsTableUnassignedFilter
                  | AccountsTableRelationshipFilter
                  | AccountsTableAccountIdFilter
                  | AccountsTableAccountFieldFilter
                  | AccountsTableCustomPropertyFilter
              > | null)
            | undefined;
        includeChurned?: (boolean | null) | undefined;
        includeIgnored?: (boolean | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        metrics?:
            | (Array<
                  | AccountsTableCountMetric
                  | AccountsTableAggregateMetric
                  | AccountsTableCountThresholdMetric
              > | null)
            | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        response?: (AccountsTableQueryResponse | null) | undefined;
        sort?: (AccountsTableSort | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    /**
     * * `contains` - contains
     * * `regex` - regex
     * * `exact` - exact
     */
    export type ActionStepMatchingEnum = "contains" | "regex" | "exact";
    export type NullEnum = null;
    export type ActionStepJSON = {
        event?: (string | null) | undefined;
        properties?: (Array<ActionStepPropertyFilter> | null) | undefined;
        selector?: (string | null) | undefined;
        selector_regex: string | null;
        tag_name?: (string | null) | undefined;
        text?: (string | null) | undefined;
        text_matching?: (ActionStepMatchingEnum | NullEnum) | undefined;
        href?: (string | null) | undefined;
        href_matching?: (ActionStepMatchingEnum | NullEnum) | undefined;
        url?: (string | null) | undefined;
        url_matching?: (ActionStepMatchingEnum | NullEnum) | undefined;
    };
    /**
     * * `engineering` - Engineering
     * * `data` - Data
     * * `product` - Product Management
     * * `founder` - Founder
     * * `leadership` - Leadership
     * * `marketing` - Marketing
     * * `sales` - Sales / Success
     * * `student` - Student
     * * `other` - Other
     */
    export type RoleAtOrganizationEnum =
        | "engineering"
        | "data"
        | "product"
        | "founder"
        | "leadership"
        | "marketing"
        | "sales"
        | "student"
        | "other";
    export type BlankEnum = "";
    export type UserBasic = {
        id: number;
        uuid: string;
        distinct_id?: (string | null) | undefined;
        first_name?: string | undefined;
        last_name?: string | undefined;
        email: string;
        is_email_verified?: (boolean | null) | undefined;
        hedgehog_config: Record<string, unknown> | null;
        role_at_organization?:
            | (RoleAtOrganizationEnum | BlankEnum | NullEnum)
            | undefined;
    };
    /**
     * Serializer mixin that handles tags for objects.
     */
    export type Action = {
        id: number;
        /**
         * Serializer mixin that handles tags for objects.
         */
        name?: (string | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        description?: string | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        tags?: Array<unknown> | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        post_to_slack?: boolean | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        slack_message_format?: string | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        steps?: Array<ActionStepJSON> | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        /**
         * Serializer mixin that handles tags for objects.
         */
        deleted?: boolean | undefined;
        is_calculating: boolean;
        /**
         * Serializer mixin that handles tags for objects.
         */
        last_calculated_at?: string | undefined;
        team_id: number;
        is_action: boolean;
        bytecode_error: string | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        pinned_at?: (string | null) | undefined;
        creation_context: string | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        _create_in_folder?: string | undefined;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    export type ActionConversionGoal = { actionId: number };
    /**
     * * `event` - event
     * * `event_metadata` - event_metadata
     * * `feature` - feature
     * * `person` - person
     * * `person_metadata` - person_metadata
     * * `cohort` - cohort
     * * `element` - element
     * * `static-cohort` - static-cohort
     * * `dynamic-cohort` - dynamic-cohort
     * * `precalculated-cohort` - precalculated-cohort
     * * `group` - group
     * * `recording` - recording
     * * `log_entry` - log_entry
     * * `behavioral` - behavioral
     * * `session` - session
     * * `hogql` - hogql
     * * `data_warehouse` - data_warehouse
     * * `data_warehouse_person_property` - data_warehouse_person_property
     * * `error_tracking_issue` - error_tracking_issue
     * * `log` - log
     * * `log_attribute` - log_attribute
     * * `log_resource_attribute` - log_resource_attribute
     * * `metric_attribute` - metric_attribute
     * * `span` - span
     * * `span_attribute` - span_attribute
     * * `span_resource_attribute` - span_resource_attribute
     * * `revenue_analytics` - revenue_analytics
     * * `account_custom_property` - account_custom_property
     * * `flag` - flag
     * * `workflow_variable` - workflow_variable
     */
    export type PropertyFilterTypeEnum =
        | "event"
        | "event_metadata"
        | "feature"
        | "person"
        | "person_metadata"
        | "cohort"
        | "element"
        | "static-cohort"
        | "dynamic-cohort"
        | "precalculated-cohort"
        | "group"
        | "recording"
        | "log_entry"
        | "behavioral"
        | "session"
        | "hogql"
        | "data_warehouse"
        | "data_warehouse_person_property"
        | "error_tracking_issue"
        | "log"
        | "log_attribute"
        | "log_resource_attribute"
        | "metric_attribute"
        | "span"
        | "span_attribute"
        | "span_resource_attribute"
        | "revenue_analytics"
        | "account_custom_property"
        | "flag"
        | "workflow_variable";
    /**
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `starts_with` - starts_with
     * * `not_starts_with` - not_starts_with
     * * `ends_with` - ends_with
     * * `not_ends_with` - not_ends_with
     * * `regex` - regex
     * * `not_regex` - not_regex
     */
    export type StringMatchOperatorEnum =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "starts_with"
        | "not_starts_with"
        | "ends_with"
        | "not_ends_with"
        | "regex"
        | "not_regex";
    /**
     * Matches string values with text-oriented operators.
     */
    export type StringPropertyFilter = {
        /**
         * Key of the property you're filtering on. For example `email` or `$current_url`.
         */
        key: string;
        /**
         * Matches string values with text-oriented operators.
         */
        type?: (PropertyFilterTypeEnum & unknown) | undefined;
        /**
         * String value to match against.
         */
        value: string;
        /**
         * Matches string values with text-oriented operators.
         */
        operator?: (StringMatchOperatorEnum & unknown) | undefined;
    };
    /**
     * * `exact` - exact
     * * `is_not` - is_not
     * * `gt` - gt
     * * `lt` - lt
     * * `gte` - gte
     * * `lte` - lte
     */
    export type NumericPropertyFilterOperatorEnum =
        | "exact"
        | "is_not"
        | "gt"
        | "lt"
        | "gte"
        | "lte";
    /**
     * Matches numeric values with comparison operators.
     */
    export type NumericPropertyFilter = {
        /**
         * Key of the property you're filtering on. For example `email` or `$current_url`.
         */
        key: string;
        /**
         * Matches numeric values with comparison operators.
         */
        type?: (PropertyFilterTypeEnum & unknown) | undefined;
        /**
         * Numeric value to compare against.
         */
        value: number;
        /**
         * Matches numeric values with comparison operators.
         */
        operator?: (NumericPropertyFilterOperatorEnum & unknown) | undefined;
    };
    /**
     * * `exact` - exact
     * * `is_not` - is_not
     * * `in` - in
     * * `not_in` - not_in
     */
    export type ArrayPropertyFilterOperatorEnum =
        | "exact"
        | "is_not"
        | "in"
        | "not_in";
    /**
     * Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in).
     */
    export type ArrayPropertyFilter = {
        /**
         * Key of the property you're filtering on. For example `email` or `$current_url`.
         */
        key: string;
        /**
         * Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in).
         */
        type?: (PropertyFilterTypeEnum & unknown) | undefined;
        /**
         * List of values to match. For example `["test@example.com", "ok@example.com"]`.
         */
        value: Array<string>;
        /**
         * Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in).
         */
        operator?: (ArrayPropertyFilterOperatorEnum & unknown) | undefined;
    };
    /**
     * * `is_date_exact` - is_date_exact
     * * `is_date_before` - is_date_before
     * * `is_date_after` - is_date_after
     */
    export type DateOperatorEnum =
        | "is_date_exact"
        | "is_date_before"
        | "is_date_after";
    /**
     * Matches date/datetime values with date-specific operators.
     */
    export type DatePropertyFilter = {
        /**
         * Key of the property you're filtering on. For example `email` or `$current_url`.
         */
        key: string;
        /**
         * Matches date/datetime values with date-specific operators.
         */
        type?: (PropertyFilterTypeEnum & unknown) | undefined;
        /**
         * Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z').
         */
        value: string;
        /**
         * Matches date/datetime values with date-specific operators.
         */
        operator?: (DateOperatorEnum & unknown) | undefined;
    };
    /**
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set
     */
    export type ExistenceOperatorEnum = "is_set" | "is_not_set";
    /**
     * Checks whether a property is set or not, without comparing values.
     */
    export type ExistencePropertyFilter = {
        /**
         * Key of the property you're filtering on. For example `email` or `$current_url`.
         */
        key: string;
        /**
         * Checks whether a property is set or not, without comparing values.
         */
        type?: (PropertyFilterTypeEnum & unknown) | undefined;
        /**
         * Existence check operator.
         *
         * * `is_set` - is_set
         * * `is_not_set` - is_not_set
         */
        operator: ExistenceOperatorEnum;
    };
    export type ActionStepPropertyFilter =
        | StringPropertyFilter
        | NumericPropertyFilter
        | ArrayPropertyFilter
        | DatePropertyFilter
        | ExistencePropertyFilter;
    export type EventPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator?: (PropertyOperator | null) | undefined;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type PersonPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type PersonMetadataPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type Key10 = "tag_name" | "text" | "href" | "selector";
    export type ElementPropertyFilter = {
        key: Key10;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type EventMetadataPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type SessionPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type CohortPropertyFilter = {
        cohort_name?: (string | null) | undefined;
        key?: string | undefined;
        label?: (string | null) | undefined;
        operator?: (PropertyOperator | null) | undefined;
        type?: string | undefined;
        value: number;
    };
    export type DurationType =
        | "duration"
        | "active_seconds"
        | "inactive_seconds";
    export type RecordingPropertyFilter = {
        key: DurationType | string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type LogEntryPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type GroupPropertyFilter = {
        group_key_names?: (Record<string, string> | null) | undefined;
        group_type_index?: (number | null) | undefined;
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type FeaturePropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type FlagPropertyFilter = {
        /**
         * The key should be the flag ID
         */
        key: string;
        label?: (string | null) | undefined;
        operator?: string | undefined;
        type?: string | undefined;
        /**
         * The value can be true, false, or a variant name
         */
        value: boolean | string;
    };
    export type HogQLPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type EmptyPropertyFilter = Partial<{ type: string }>;
    export type DataWarehousePropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type DataWarehousePersonPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type ErrorTrackingIssueFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type LogPropertyFilterType =
        | "log"
        | "log_attribute"
        | "log_resource_attribute";
    export type LogPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type: LogPropertyFilterType;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type MetricPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type SpanPropertyFilterType =
        | "span"
        | "span_attribute"
        | "span_resource_attribute";
    export type SpanPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type: SpanPropertyFilterType;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type RevenueAnalyticsPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type WorkflowVariablePropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type?: string | undefined;
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type BehavioralEventSource = "events" | "actions";
    export type TimeUnitType = "day" | "week" | "month" | "year";
    export type InlineBehavioralType =
        | "performed_event"
        | "performed_event_multiple";
    export type BehavioralPropertyFilter = {
        event_filters?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | FeaturePropertyFilter
                  | HogQLPropertyFilter
              > | null)
            | undefined;
        event_type: BehavioralEventSource;
        explicit_datetime?: (string | null) | undefined;
        explicit_datetime_to?: (string | null) | undefined;
        /**
         * Event name, or action id when event_type is 'actions'
         */
        key: string;
        label?: (string | null) | undefined;
        negation?: (boolean | null) | undefined;
        operator?: (PropertyOperator | null) | undefined;
        operator_value?: (number | null) | undefined;
        time_interval?: (TimeUnitType | null) | undefined;
        time_value?: (number | null) | undefined;
        type?: string | undefined;
        value: InlineBehavioralType;
    };
    export type BaseMathType =
        | "total"
        | "dau"
        | "weekly_active"
        | "monthly_active"
        | "unique_session"
        | "first_time_for_user"
        | "first_matching_event_for_user";
    export type FunnelMathType =
        | "total"
        | "first_time_for_user"
        | "first_time_for_user_with_filters";
    export type PropertyMathType =
        | "avg"
        | "sum"
        | "min"
        | "max"
        | "median"
        | "p75"
        | "p90"
        | "p95"
        | "p99";
    export type CountPerActorMathType =
        | "avg_count_per_actor"
        | "min_count_per_actor"
        | "max_count_per_actor"
        | "median_count_per_actor"
        | "p75_count_per_actor"
        | "p90_count_per_actor"
        | "p95_count_per_actor"
        | "p99_count_per_actor";
    export type GroupMathType =
        | "unique_group"
        | "first_time_for_group"
        | "first_matching_event_for_group";
    export type ExperimentMetricMathType =
        | "total"
        | "sum"
        | "unique_session"
        | "min"
        | "max"
        | "avg"
        | "dau"
        | "unique_group"
        | "hogql";
    export type CalendarHeatmapMathType = "total" | "dau";
    export type MathGroupTypeIndex = 0 | 1 | 2 | 3 | 4;
    export type CurrencyCode =
        | "AED"
        | "AFN"
        | "ALL"
        | "AMD"
        | "ANG"
        | "AOA"
        | "ARS"
        | "AUD"
        | "AWG"
        | "AZN"
        | "BAM"
        | "BBD"
        | "BDT"
        | "BGN"
        | "BHD"
        | "BIF"
        | "BMD"
        | "BND"
        | "BOB"
        | "BRL"
        | "BSD"
        | "BTC"
        | "BTN"
        | "BWP"
        | "BYN"
        | "BZD"
        | "CAD"
        | "CDF"
        | "CHF"
        | "CLP"
        | "CNY"
        | "COP"
        | "CRC"
        | "CVE"
        | "CZK"
        | "DJF"
        | "DKK"
        | "DOP"
        | "DZD"
        | "EGP"
        | "ERN"
        | "ETB"
        | "EUR"
        | "FJD"
        | "GBP"
        | "GEL"
        | "GHS"
        | "GIP"
        | "GMD"
        | "GNF"
        | "GTQ"
        | "GYD"
        | "HKD"
        | "HNL"
        | "HRK"
        | "HTG"
        | "HUF"
        | "IDR"
        | "ILS"
        | "INR"
        | "IQD"
        | "IRR"
        | "ISK"
        | "JMD"
        | "JOD"
        | "JPY"
        | "KES"
        | "KGS"
        | "KHR"
        | "KMF"
        | "KRW"
        | "KWD"
        | "KYD"
        | "KZT"
        | "LAK"
        | "LBP"
        | "LKR"
        | "LRD"
        | "LTL"
        | "LVL"
        | "LSL"
        | "LYD"
        | "MAD"
        | "MDL"
        | "MGA"
        | "MKD"
        | "MMK"
        | "MNT"
        | "MOP"
        | "MRU"
        | "MTL"
        | "MUR"
        | "MVR"
        | "MWK"
        | "MXN"
        | "MYR"
        | "MZN"
        | "NAD"
        | "NGN"
        | "NIO"
        | "NOK"
        | "NPR"
        | "NZD"
        | "OMR"
        | "PAB"
        | "PEN"
        | "PGK"
        | "PHP"
        | "PKR"
        | "PLN"
        | "PYG"
        | "QAR"
        | "RON"
        | "RSD"
        | "RUB"
        | "RWF"
        | "SAR"
        | "SBD"
        | "SCR"
        | "SDG"
        | "SEK"
        | "SGD"
        | "SRD"
        | "SSP"
        | "STN"
        | "SYP"
        | "SZL"
        | "THB"
        | "TJS"
        | "TMT"
        | "TND"
        | "TOP"
        | "TRY"
        | "TTD"
        | "TWD"
        | "TZS"
        | "UAH"
        | "UGX"
        | "USD"
        | "UYU"
        | "UZS"
        | "VES"
        | "VND"
        | "VUV"
        | "WST"
        | "XAF"
        | "XCD"
        | "XOF"
        | "XPF"
        | "YER"
        | "ZAR"
        | "ZMW";
    export type RevenueCurrencyPropertyConfig = Partial<{
        property: string | null;
        static: CurrencyCode | null;
    }>;
    export type ActionsNode = {
        custom_name?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        id: number;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ActionsPie = Partial<{
        disableHoverOffset: boolean | null;
        hideAggregation: boolean | null;
    }>;
    export type PropertyGroupFilterValue = {
        type: FilterLogicalOperator;
        values: Array<
            | PropertyGroupFilterValue
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        >;
    };
    export type ActorsQueryResponse = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        limit: number;
        missing_actors_count?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<string> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Compare = "current" | "previous";
    export type BreakdownType =
        | "cohort"
        | "person"
        | "event"
        | "event_metadata"
        | "group"
        | "session"
        | "hogql"
        | "data_warehouse"
        | "data_warehouse_person_property"
        | "revenue_analytics";
    export type MultipleBreakdownType =
        | "person"
        | "event"
        | "event_metadata"
        | "group"
        | "session"
        | "hogql"
        | "cohort"
        | "revenue_analytics"
        | "data_warehouse"
        | "data_warehouse_person_property";
    export type Breakdown = {
        group_type_index?: (number | null) | undefined;
        histogram_bin_count?: (number | null) | undefined;
        normalize_url?: (boolean | null) | undefined;
        property: string | number;
        type?: (MultipleBreakdownType | null) | undefined;
    };
    export type BreakdownFilter = Partial<{
        breakdown: string | Array<string | number> | number | null;
        breakdown_group_type_index: number | null;
        breakdown_hide_other_aggregation: boolean | null;
        breakdown_histogram_bin_count: number | null;
        breakdown_limit: number | null;
        breakdown_normalize_url: boolean | null;
        breakdown_path_cleaning: boolean | null;
        breakdown_type: BreakdownType | null;
        breakdowns: Array<Breakdown> | null;
    }>;
    export type CalendarHeatmapFilter = Partial<{
        bucketBySessionStart: boolean | null;
    }>;
    export type CompareFilter = Partial<{
        compare: boolean | null;
        compare_to: string | null;
    }>;
    export type CustomEventConversionGoal = { customEventName: string };
    export type DaysOfWeekEnum = 1 | 2 | 3 | 4 | 5 | 6 | 7;
    export type DateRange = Partial<{
        date_from: string | null;
        date_to: string | null;
        daysOfWeek: Array<DaysOfWeekEnum> | null;
        excludeIncompletePeriods: boolean | null;
        explicitDate: boolean | null;
    }>;
    export type IntervalType =
        | "second"
        | "minute"
        | "hour"
        | "day"
        | "week"
        | "month"
        | "quarter"
        | "year";
    export type PropertyGroupFilter = {
        type: FilterLogicalOperator;
        values: Array<PropertyGroupFilterValue>;
    };
    export type BoxPlotDatum = {
        day: string;
        label: string;
        max: number;
        mean: number;
        median: number;
        min: number;
        p25: number;
        p75: number;
        series_index?: (number | null) | undefined;
        series_label?: (string | null) | undefined;
    };
    export type TrendsQueryResponse = {
        boxplot_data?: (Array<BoxPlotDatum> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Record<string, unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type EventsNode = Partial<{
        custom_name: string | null;
        event: string | null;
        fixedProperties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        kind: string;
        limit: number | null;
        math:
            | BaseMathType
            | FunnelMathType
            | PropertyMathType
            | CountPerActorMathType
            | GroupMathType
            | ExperimentMetricMathType
            | CalendarHeatmapMathType
            | string
            | null;
        math_group_type_index: MathGroupTypeIndex | null;
        math_hogql: string | null;
        math_multiplier: number | null;
        math_property: string | null;
        math_property_revenue_currency: RevenueCurrencyPropertyConfig | null;
        math_property_type: string | null;
        name: string | null;
        optionalInFunnel: boolean | null;
        orderBy: Array<string> | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        response: Record<string, unknown> | null;
        version: number | null;
    }>;
    export type DataWarehouseNode = {
        custom_name?: (string | null) | undefined;
        distinct_id_field: string;
        dw_source_type?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        id: string;
        id_field: string;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        table_name: string;
        timestamp_field: string;
        version?: (number | null) | undefined;
    };
    export type GroupNode = {
        custom_name?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        /**
         * Entities to combine in this group
         */
        nodes: Array<EventsNode | ActionsNode | DataWarehouseNode>;
        /**
         * Group of entities combined with AND/OR operator
         */
        operator: FilterLogicalOperator;
        optionalInFunnel?: (boolean | null) | undefined;
        orderBy?: (Array<string> | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type AggregationAxisFormat =
        | "numeric"
        | "duration"
        | "duration_ms"
        | "duration_ns"
        | "percentage"
        | "percentage_scaled"
        | "currency"
        | "short";
    export type Curve = "linear" | "smooth";
    export type ChartStyle = Partial<{ curve: Curve | null }>;
    export type DetailedResultsAggregationType = "total" | "average" | "median";
    export type ChartDisplayType =
        | "Auto"
        | "ActionsLineGraph"
        | "ActionsBar"
        | "ActionsUnstackedBar"
        | "ActionsStackedBar"
        | "ActionsAreaGraph"
        | "ActionsLineGraphCumulative"
        | "BoldNumber"
        | "Metric"
        | "ActionsPie"
        | "ActionsDonut"
        | "ActionsBarValue"
        | "ActionsTable"
        | "WorldMap"
        | "CalendarHeatmap"
        | "TwoDimensionalHeatmap"
        | "BoxPlot"
        | "SlopeGraph"
        | "ScatterPlot";
    export type TrendsFormulaNode = {
        custom_name?: (string | null) | undefined;
        formula: string;
    };
    export type Position = "start" | "end";
    export type GoalLine = {
        borderColor?: (string | null) | undefined;
        displayIfCrossed?: (boolean | null) | undefined;
        displayLabel?: (boolean | null) | undefined;
        label: string;
        position?: (Position | null) | undefined;
        value: number;
    };
    export type LegendPosition = "top" | "bottom" | "left" | "right";
    export type MetricSummary = "total" | "average" | "latest";
    export type ResultCustomizationBy = "value" | "position";
    export type DataColorToken =
        | "preset-1"
        | "preset-2"
        | "preset-3"
        | "preset-4"
        | "preset-5"
        | "preset-6"
        | "preset-7"
        | "preset-8"
        | "preset-9"
        | "preset-10"
        | "preset-11"
        | "preset-12"
        | "preset-13"
        | "preset-14"
        | "preset-15";
    export type ResultCustomizationByValue = Partial<{
        assignmentBy: string;
        color: DataColorToken | null;
        hidden: boolean | null;
    }>;
    export type ResultCustomizationByPosition = Partial<{
        assignmentBy: string;
        color: DataColorToken | null;
        hidden: boolean | null;
    }>;
    export type YAxisScaleType = "log10" | "linear";
    export type TrendsFilter = Partial<{
        aggregationAxisFormat: AggregationAxisFormat | null;
        aggregationAxisPostfix: string | null;
        aggregationAxisPrefix: string | null;
        breakdown_histogram_bin_count: number | null;
        chartStyle: ChartStyle | null;
        confidenceLevel: number | null;
        decimalPlaces: number | null;
        detailedResultsAggregationType: DetailedResultsAggregationType | null;
        display: ChartDisplayType | null;
        excludeBoxPlotOutliers: boolean | null;
        formula: string | null;
        formulaNodes: Array<TrendsFormulaNode> | null;
        formulas: Array<string> | null;
        goalLines: Array<GoalLine> | null;
        hiddenLegendIndexes: Array<number> | null;
        hideWeekends: boolean | null;
        legendPosition: LegendPosition | null;
        metricChangeDecreaseColor: string | null;
        metricChangeIncreaseColor: string | null;
        metricColorByDirection: boolean | null;
        metricLineDecreaseColor: string | null;
        metricLineIncreaseColor: string | null;
        metricShowChange: boolean | null;
        metricSummary: MetricSummary | null;
        minDecimalPlaces: number | null;
        movingAverageIntervals: number | null;
        resultCustomizationBy: ResultCustomizationBy | null;
        resultCustomizations:
            | Record<string, ResultCustomizationByValue>
            | Record<string, ResultCustomizationByPosition>
            | null;
        showAlertThresholdLines: boolean | null;
        showAnnotations: boolean | null;
        showConfidenceIntervals: boolean | null;
        showLabelsOnSeries: boolean | null;
        showLegend: boolean | null;
        showMovingAverage: boolean | null;
        showMultipleYAxes: boolean | null;
        showPercentStackView: boolean | null;
        showTrendLines: boolean | null;
        showValuesOnSeries: boolean | null;
        smoothingIntervals: number | null;
        stackBreakdownValues: boolean | null;
        xAxisLabel: string | null;
        yAxisLabel: string | null;
        yAxisMax: number | null;
        yAxisMin: number | null;
        yAxisScaleType: YAxisScaleType | null;
        yAxisStartAtZero: boolean | null;
    }>;
    export type TrendsQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        calendarHeatmapFilter?: (CalendarHeatmapFilter | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties?:
            | (
                  | Array<
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    >
                  | PropertyGroupFilter
                  | null
              )
            | undefined;
        response?: (TrendsQueryResponse | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        /**
         * Events and actions to include
         */
        series: Array<EventsNode | ActionsNode | DataWarehouseNode | GroupNode>;
        tags?: (QueryLogTags | null) | undefined;
        trendsFilter?: (TrendsFilter | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type BreakdownAttributionType =
        | "first_touch"
        | "last_touch"
        | "all_events"
        | "step";
    export type FunnelExclusionEventsNode = {
        custom_name?: (string | null) | undefined;
        event?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        funnelFromStep: number;
        funnelToStep: number;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        orderBy?: (Array<string> | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type FunnelExclusionActionsNode = {
        custom_name?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        funnelFromStep: number;
        funnelToStep: number;
        id: number;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type StepOrderValue = "strict" | "unordered" | "ordered";
    export type FunnelStepReference = "total" | "previous";
    export type FunnelVizType = "steps" | "time_to_convert" | "trends" | "flow";
    export type FunnelConversionWindowTimeUnit =
        | "second"
        | "minute"
        | "hour"
        | "day"
        | "week"
        | "month";
    export type FunnelLayout = "horizontal" | "vertical";
    export type FunnelsFilter = Partial<{
        binCount: number | null;
        breakdownAttributionType: BreakdownAttributionType | null;
        breakdownAttributionValue: number | null;
        breakdownSorting: string | null;
        chartStyle: ChartStyle | null;
        customAggregationTarget: boolean | null;
        exclusions: Array<
            FunnelExclusionEventsNode | FunnelExclusionActionsNode
        > | null;
        funnelAggregateByHogQL: string | null;
        funnelFromStep: number | null;
        funnelOrderType: StepOrderValue | null;
        funnelStepReference: FunnelStepReference | null;
        funnelToStep: number | null;
        funnelVizType: FunnelVizType | null;
        funnelWindowInterval: number | null;
        funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | null;
        goalLines: Array<GoalLine> | null;
        hiddenLegendBreakdowns: Array<string> | null;
        hideIncompleteConversionWindowPeriods: boolean | null;
        layout: FunnelLayout | null;
        legendPosition: LegendPosition | null;
        resultCustomizations: Record<string, ResultCustomizationByValue> | null;
        showAnnotations: boolean | null;
        showLegend: boolean | null;
        showTrendLines: boolean | null;
        showValuesOnSeries: boolean | null;
        useUdf: boolean | null;
    }>;
    export type FunnelsQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: unknown;
        timings?: (Array<QueryTiming> | null) | undefined;
        total_median_conversion_time?: (number | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type FunnelsDataWarehouseNode = {
        aggregation_target_field: string;
        custom_name?: (string | null) | undefined;
        dw_source_type?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        id: string;
        id_field: string;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        table_name: string;
        timestamp_field: string;
        version?: (number | null) | undefined;
    };
    export type FunnelsQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        funnelsFilter?: (FunnelsFilter | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties?:
            | (
                  | Array<
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    >
                  | PropertyGroupFilter
                  | null
              )
            | undefined;
        response?: (FunnelsQueryResponse | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        /**
         * Events and actions to include
         */
        series: Array<
            EventsNode | ActionsNode | FunnelsDataWarehouseNode | GroupNode
        >;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type RetentionValue = {
        aggregation_value?: (number | null) | undefined;
        count: number;
        label?: (string | null) | undefined;
    };
    export type RetentionResult = {
        breakdown_value?: (string | number | null) | undefined;
        date: string;
        label: string;
        values: Array<RetentionValue>;
    };
    export type RetentionQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<RetentionResult>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type AggregationPropertyType = "event" | "person" | "data_warehouse";
    export type AggregationType = "count" | "sum" | "avg";
    export type RetentionDashboardDisplayType =
        | "table_only"
        | "graph_only"
        | "all";
    export type MeanRetentionCalculation = "simple" | "weighted" | "none";
    export type RetentionPeriod = "Hour" | "Day" | "Week" | "Month";
    export type RetentionReference = "total" | "previous";
    export type RetentionType =
        | "retention_recurring"
        | "retention_first_time"
        | "retention_first_ever_occurrence";
    export type RetentionEntityKind = "ActionsNode" | "EventsNode";
    export type EntityType =
        | "actions"
        | "events"
        | "data_warehouse"
        | "new_entity"
        | "groups";
    export type RetentionEntity = Partial<{
        aggregation_target_field: string | null;
        custom_name: string | null;
        id: string | number | null;
        kind: RetentionEntityKind | null;
        name: string | null;
        order: number | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        table_name: string | null;
        timestamp_field: string | null;
        type: EntityType | null;
        uuid: string | null;
    }>;
    export type TimeWindowMode = "strict_calendar_dates" | "24_hour_windows";
    export type RetentionFilter = Partial<{
        aggregationProperty: string | null;
        aggregationPropertyType: AggregationPropertyType | null;
        aggregationType: AggregationType | null;
        chartStyle: ChartStyle | null;
        cohortLabelStartIndex: number | null;
        cumulative: boolean | null;
        customAggregationTarget: boolean | null;
        dashboardDisplay: RetentionDashboardDisplayType | null;
        display: ChartDisplayType | null;
        goalLines: Array<GoalLine> | null;
        meanRetentionCalculation: MeanRetentionCalculation | null;
        minimumOccurrences: number | null;
        period: RetentionPeriod | null;
        retentionCustomBrackets: Array<number> | null;
        retentionReference: RetentionReference | null;
        retentionType: RetentionType | null;
        returningEntity: RetentionEntity | null;
        selectedInterval: number | null;
        showTrendLines: boolean | null;
        targetEntity: RetentionEntity | null;
        timeWindowMode: TimeWindowMode | null;
        totalIntervals: number | null;
    }>;
    export type RetentionQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties?:
            | (
                  | Array<
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    >
                  | PropertyGroupFilter
                  | null
              )
            | undefined;
        response?: (RetentionQueryResponse | null) | undefined;
        /**
         * Properties specific to the retention insight
         */
        retentionFilter: RetentionFilter;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type FunnelPathType =
        | "funnel_path_before_step"
        | "funnel_path_between_steps"
        | "funnel_path_after_step";
    export type FunnelPathsFilter = {
        funnelPathType?: (FunnelPathType | null) | undefined;
        funnelSource: FunnelsQuery;
        funnelStep?: (number | null) | undefined;
    };
    export type PathType = "$pageview" | "$screen" | "custom_event" | "hogql";
    export type PathCleaningFilter = Partial<{
        alias: string | null;
        order: number | null;
        regex: string | null;
    }>;
    export type PathsFilter = Partial<{
        edgeLimit: number | null;
        endPoint: string | null;
        excludeEvents: Array<string> | null;
        includeEventTypes: Array<PathType> | null;
        localPathCleaningFilters: Array<PathCleaningFilter> | null;
        maxEdgeWeight: number | null;
        minEdgeWeight: number | null;
        pathDropoffKey: string | null;
        pathEndKey: string | null;
        pathGroupings: Array<string> | null;
        pathReplacements: boolean | null;
        pathStartKey: string | null;
        pathsHogQLExpression: string | null;
        showFullUrls: boolean | null;
        startPoint: string | null;
        stepLimit: number | null;
    }>;
    export type PathsLink = {
        average_conversion_time: number;
        source: string;
        target: string;
        value: number;
    };
    export type PathsQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<PathsLink>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type PathsQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        funnelPathsFilter?: (FunnelPathsFilter | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        /**
         * Properties specific to the paths insight
         */
        pathsFilter: PathsFilter;
        properties?:
            | (
                  | Array<
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    >
                  | PropertyGroupFilter
                  | null
              )
            | undefined;
        response?: (PathsQueryResponse | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type PathsV2Item = {
        /**
         * Event of the step source this item belongs to.
         */
        event: string;
        label?: (string | null) | undefined;
    };
    export type PathsV2AnchorType = "start" | "end";
    export type PathsV2Anchor = {
        /**
         * The path item the chart anchors on. Its event must be one of the step sources.
         */
        item: PathsV2Item;
        /**
         * `start` runs each actor's single sequence forward from the anchor item; `end` runs it up to the anchor item. Either way the anchor is the grid's single 100% node.
         */
        type: PathsV2AnchorType;
    };
    export type PathsV2StepSource = {
        /**
         * Name of the event this source matches.
         */
        event: string;
        namingProperty?: (string | null) | undefined;
    };
    export type PathsV2Filter = Partial<{
        anchor: PathsV2Anchor | null;
        applyTeamPathCleaning: boolean | null;
        collapseRepeats: boolean | null;
        conversionWindowInterval: number | null;
        conversionWindowIntervalUnit: FunnelConversionWindowTimeUnit | null;
        excludedItems: Array<PathsV2Item> | null;
        gapInterval: number | null;
        gapIntervalUnit: FunnelConversionWindowTimeUnit | null;
        localPathCleaningFilters: Array<PathCleaningFilter> | null;
        maxRowsPerStep: number | null;
        maxSteps: number | null;
        stepSources: Array<PathsV2StepSource> | null;
    }>;
    export type PathsV2Edge = {
        anyStepCount?: (number | null) | undefined;
        /**
         * Unique actors with a journey that transitions from source to target between these steps.
         */
        count: number;
        /**
         * Source path item, or null for the source column's "other" row.
         */
        source: PathsV2Item | null;
        /**
         * 0-based step index of the source column; the target sits at `stepIndex + 1`.
         */
        stepIndex: number;
        /**
         * Target path item, or null for the target column's "other" row.
         */
        target: PathsV2Item | null;
    };
    export type PathsV2Prefix = {
        /**
         * Unique actors whose anchored sequence begins with exactly these items.
         */
        count: number;
        /**
         * The chain's path items in order, starting at the anchor.
         */
        items: Array<PathsV2Item>;
    };
    export type PathsV2Row = {
        /**
         * Unique actors with a journey whose item at this step is this path item.
         */
        count: number;
        item: PathsV2Item;
    };
    export type PathsV2Step = {
        /**
         * Unique actors whose journey ends at this step.
         */
        dropOffCount: number;
        /**
         * Unique actors at this step whose path item is beyond the top rows.
         */
        otherCount: number;
        /**
         * Top path items at this step, ordered by unique-actor count descending.
         */
        rows: Array<PathsV2Row>;
        /**
         * 0-based step index (column) in the journey grid.
         */
        stepIndex: number;
    };
    export type PathsV2Results = {
        edges: Array<PathsV2Edge>;
        /**
         * Concrete anchored chains with per-chain unique-actor counts, ordered by descending count. Empty in open mode; in anchored mode it carries the counts the hover funnel preview reads per chain. Only chains the grid displays in full are carried: chains through the other bucket are omitted, so the response never exposes labels the chart hides.
         */
        prefixes: Array<PathsV2Prefix>;
        steps: Array<PathsV2Step>;
    };
    export type PathsV2QueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: PathsV2Results;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type PathsV2Query = Partial<{
        dataColorTheme: number | null;
        dateRange: DateRange | null;
        filterTestAccounts: boolean | null;
        kind: string;
        modifiers: HogQLQueryModifiers | null;
        pathsV2Filter: PathsV2Filter | null;
        properties:
            | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              >
            | PropertyGroupFilter
            | null;
        response: PathsV2QueryResponse | null;
        tags: QueryLogTags | null;
        version: number | null;
    }>;
    export type StickinessQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Record<string, unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type StickinessComputationMode = "non_cumulative" | "cumulative";
    export type StickinessOperator = "gte" | "lte" | "exact";
    export type StickinessCriteria = {
        operator: StickinessOperator;
        value: number;
    };
    export type StickinessFilter = Partial<{
        chartStyle: ChartStyle | null;
        computedAs: StickinessComputationMode | null;
        display: ChartDisplayType | null;
        hiddenLegendIndexes: Array<number> | null;
        legendPosition: LegendPosition | null;
        resultCustomizationBy: ResultCustomizationBy | null;
        resultCustomizations:
            | Record<string, ResultCustomizationByValue>
            | Record<string, ResultCustomizationByPosition>
            | null;
        showLegend: boolean | null;
        showMultipleYAxes: boolean | null;
        showValuesOnSeries: boolean | null;
        stickinessCriteria: StickinessCriteria | null;
    }>;
    export type StickinessQuery = {
        compareFilter?: (CompareFilter | null) | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        intervalCount?: (number | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties?:
            | (
                  | Array<
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    >
                  | PropertyGroupFilter
                  | null
              )
            | undefined;
        response?: (StickinessQueryResponse | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        /**
         * Events and actions to include
         */
        series: Array<EventsNode | ActionsNode | DataWarehouseNode>;
        stickinessFilter?: (StickinessFilter | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type LifecycleToggle =
        | "new"
        | "resurrecting"
        | "returning"
        | "dormant";
    export type LifecycleFilter = Partial<{
        legendPosition: LegendPosition | null;
        showLegend: boolean | null;
        showPercentagesOnSeries: boolean | null;
        showValuesOnSeries: boolean | null;
        stacked: boolean | null;
        toggledLifecycles: Array<LifecycleToggle> | null;
    }>;
    export type LifecycleQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Record<string, unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type LifecycleDataWarehouseNode = {
        aggregation_target_field: string;
        created_at_field: string;
        custom_name?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        id: string;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        table_name: string;
        timestamp_field: string;
        version?: (number | null) | undefined;
    };
    export type LifecycleQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        customAggregationTarget?: (boolean | null) | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        lifecycleFilter?: (LifecycleFilter | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties?:
            | (
                  | Array<
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    >
                  | PropertyGroupFilter
                  | null
              )
            | undefined;
        response?: (LifecycleQueryResponse | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        /**
         * Events and actions to include
         */
        series: Array<EventsNode | ActionsNode | LifecycleDataWarehouseNode>;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebStatsBreakdown =
        | "Page"
        | "InitialPage"
        | "ExitPage"
        | "ExitClick"
        | "PreviousPage"
        | "ScreenName"
        | "InitialChannelType"
        | "InitialReferringDomain"
        | "InitialReferringURL"
        | "InitialUTMSource"
        | "InitialUTMCampaign"
        | "InitialUTMMedium"
        | "InitialUTMTerm"
        | "InitialUTMContent"
        | "InitialUTMSourceMediumCampaign"
        | "FirstPageviewChannelType"
        | "FirstPageviewReferringDomain"
        | "FirstPageviewUTMSource"
        | "FirstPageviewUTMCampaign"
        | "FirstPageviewUTMMedium"
        | "FirstPageviewUTMTerm"
        | "FirstPageviewUTMContent"
        | "FirstPageviewUTMSourceMediumCampaign"
        | "Browser"
        | "OS"
        | "Viewport"
        | "DeviceType"
        | "Country"
        | "Region"
        | "City"
        | "Timezone"
        | "Language"
        | "FrustrationMetrics";
    export type WebAnalyticsOrderByFields =
        | "Visitors"
        | "Views"
        | "AvgTimeOnPage"
        | "Clicks"
        | "BounceRate"
        | "AverageScrollPercentage"
        | "ScrollGt80Percentage"
        | "TotalConversions"
        | "UniqueConversions"
        | "ConversionRate"
        | "ConvertingUsers"
        | "RageClicks"
        | "DeadClicks"
        | "Errors";
    export type WebAnalyticsOrderByDirection = "ASC" | "DESC";
    export type WebAnalyticsPreComputeStrategy =
        | "pre_aggregated"
        | "lazy_precompute"
        | "live";
    export type SamplingRate = {
        denominator?: (number | null) | undefined;
        numerator: number;
    };
    export type WebStatsTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStale?: (boolean | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebAnalyticsSampling = Partial<{
        enabled: boolean | null;
        forceSamplingRate: SamplingRate | null;
    }>;
    export type WebStatsTableQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        breakdownBy: WebStatsBreakdown;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeAvgTimeOnPage?: (boolean | null) | undefined;
        includeBounceRate?: (boolean | null) | undefined;
        includeHost?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        includeScrollDepth?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebStatsTableQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        useWebAnalyticsPrecompute?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebAnalyticsItemKind =
        | "unit"
        | "duration_s"
        | "percentage"
        | "currency";
    export type WebOverviewItem = {
        changeFromPreviousPct?: (number | null) | undefined;
        isIncreaseBad?: (boolean | null) | undefined;
        key: string;
        kind: WebAnalyticsItemKind;
        previous?: (number | null) | undefined;
        value?: (number | null) | undefined;
    };
    export type WebOverviewQueryResponse = {
        dateFrom?: (string | null) | undefined;
        dateTo?: (string | null) | undefined;
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<WebOverviewItem>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebOverviewQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebOverviewQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        useWebAnalyticsPrecompute?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type InsightActorsQuery = {
        breakdown?: (string | Array<string> | number | null) | undefined;
        compare?: (Compare | null) | undefined;
        day?: (string | number | null) | undefined;
        includeRecordings?: (boolean | null) | undefined;
        interval?: (number | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        response?: (ActorsQueryResponse | null) | undefined;
        series?: (number | null) | undefined;
        source:
            | TrendsQuery
            | FunnelsQuery
            | RetentionQuery
            | PathsQuery
            | PathsV2Query
            | StickinessQuery
            | LifecycleQuery
            | WebStatsTableQuery
            | WebOverviewQuery;
        status?: (string | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type FunnelsActorsQuery = {
        compare?: (Compare | null) | undefined;
        funnelStep?: (number | null) | undefined;
        funnelStepBreakdown?:
            | (
                  | number
                  | string
                  | number
                  | Array<number | string | number>
                  | null
              )
            | undefined;
        funnelTrendsDropOff?: (boolean | null) | undefined;
        funnelTrendsEntrancePeriodStart?: (string | null) | undefined;
        includeRecordings?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        response?: (ActorsQueryResponse | null) | undefined;
        source: FunnelsQuery;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type FunnelCorrelationResultsType =
        | "events"
        | "properties"
        | "event_with_properties";
    export type CorrelationType = "success" | "failure";
    export type EventDefinition = {
        elements: Array<unknown>;
        event: string;
        properties: Record<string, unknown>;
    };
    export type EventOddsRatioSerialized = {
        correlation_type: CorrelationType;
        event: EventDefinition;
        failure_count: number;
        odds_ratio: number;
        success_count: number;
    };
    export type FunnelCorrelationResult = {
        events: Array<EventOddsRatioSerialized>;
        skewed: boolean;
    };
    export type FunnelCorrelationResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: FunnelCorrelationResult;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type FunnelCorrelationQuery = {
        funnelCorrelationEventExcludePropertyNames?:
            | (Array<string> | null)
            | undefined;
        funnelCorrelationEventNames?: (Array<string> | null) | undefined;
        funnelCorrelationExcludeEventNames?: (Array<string> | null) | undefined;
        funnelCorrelationExcludeNames?: (Array<string> | null) | undefined;
        funnelCorrelationNames?: (Array<string> | null) | undefined;
        funnelCorrelationType: FunnelCorrelationResultsType;
        kind?: string | undefined;
        response?: (FunnelCorrelationResponse | null) | undefined;
        source: FunnelsActorsQuery;
        version?: (number | null) | undefined;
    };
    export type FunnelCorrelationActorsQuery = {
        funnelCorrelationPersonConverted?: (boolean | null) | undefined;
        funnelCorrelationPersonEntity?:
            | (EventsNode | ActionsNode | DataWarehouseNode | null)
            | undefined;
        funnelCorrelationPropertyValues?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        includeRecordings?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        response?: (ActorsQueryResponse | null) | undefined;
        source: FunnelCorrelationQuery;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ExperimentEventExposureConfig = {
        event: string;
        kind?: string | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        >;
        response?: (Record<string, unknown> | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type MultipleVariantHandling = "exclude" | "first_seen";
    export type ExperimentMetricGoal = "increase" | "decrease";
    export type ExperimentDataWarehouseNode = {
        custom_name?: (string | null) | undefined;
        data_warehouse_join_key: string;
        events_join_key: string;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        table_name: string;
        timestamp_field: string;
        version?: (number | null) | undefined;
    };
    export type ExperimentMeanMetric = {
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        conversion_window?: (number | null) | undefined;
        conversion_window_unit?:
            | (FunnelConversionWindowTimeUnit | null)
            | undefined;
        fingerprint?: (string | null) | undefined;
        goal?: (ExperimentMetricGoal | null) | undefined;
        ignore_zeros?: (boolean | null) | undefined;
        isSharedMetric?: (boolean | null) | undefined;
        kind?: string | undefined;
        lower_bound_percentile?: (number | null) | undefined;
        metric_type?: string | undefined;
        name?: (string | null) | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        sharedMetricId?: (number | null) | undefined;
        source: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
        threshold?: (number | null) | undefined;
        upper_bound_percentile?: (number | null) | undefined;
        uuid?: (string | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ExperimentFunnelMetric = {
        breakdownAttributionType?:
            | (BreakdownAttributionType | null)
            | undefined;
        breakdownAttributionValue?: (number | null) | undefined;
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        conversion_window?: (number | null) | undefined;
        conversion_window_unit?:
            | (FunnelConversionWindowTimeUnit | null)
            | undefined;
        fingerprint?: (string | null) | undefined;
        funnel_order_type?: (StepOrderValue | null) | undefined;
        goal?: (ExperimentMetricGoal | null) | undefined;
        isSharedMetric?: (boolean | null) | undefined;
        kind?: string | undefined;
        metric_type?: string | undefined;
        name?: (string | null) | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        series: Array<EventsNode | ActionsNode | ExperimentDataWarehouseNode>;
        sharedMetricId?: (number | null) | undefined;
        uuid?: (string | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ExperimentMetricOutlierHandling = Partial<{
        ignore_zeros: boolean | null;
        lower_bound_percentile: number | null;
        upper_bound_percentile: number | null;
    }>;
    export type ExperimentRatioMetric = {
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        conversion_window?: (number | null) | undefined;
        conversion_window_unit?:
            | (FunnelConversionWindowTimeUnit | null)
            | undefined;
        denominator: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
        denominator_outlier_handling?:
            | (ExperimentMetricOutlierHandling | null)
            | undefined;
        fingerprint?: (string | null) | undefined;
        goal?: (ExperimentMetricGoal | null) | undefined;
        isSharedMetric?: (boolean | null) | undefined;
        kind?: string | undefined;
        metric_type?: string | undefined;
        name?: (string | null) | undefined;
        numerator: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
        numerator_outlier_handling?:
            | (ExperimentMetricOutlierHandling | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        sharedMetricId?: (number | null) | undefined;
        uuid?: (string | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type StartHandling = "first_seen" | "last_seen";
    export type ExperimentRetentionMetric = {
        breakdownFilter?: (BreakdownFilter | null) | undefined;
        completion_event:
            | EventsNode
            | ActionsNode
            | ExperimentDataWarehouseNode;
        conversion_window?: (number | null) | undefined;
        conversion_window_unit?:
            | (FunnelConversionWindowTimeUnit | null)
            | undefined;
        fingerprint?: (string | null) | undefined;
        goal?: (ExperimentMetricGoal | null) | undefined;
        isSharedMetric?: (boolean | null) | undefined;
        kind?: string | undefined;
        metric_type?: string | undefined;
        name?: (string | null) | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        retention_window_end: number;
        retention_window_start: number;
        retention_window_unit: FunnelConversionWindowTimeUnit;
        sharedMetricId?: (number | null) | undefined;
        start_event: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
        start_handling: StartHandling;
        uuid?: (string | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type PrecomputationMode = "precomputed" | "direct";
    export type SessionData = {
        event_uuid: string;
        person_id: string;
        session_id: string;
        timestamp: string;
    };
    export type ExperimentStatsValidationFailure =
        | "not-enough-exposures"
        | "baseline-mean-is-zero"
        | "not-enough-metric-data";
    export type ExperimentStatsBaseValidated = {
        covariate_sum?: (number | null) | undefined;
        covariate_sum_product?: (number | null) | undefined;
        covariate_sum_squares?: (number | null) | undefined;
        denominator_sum?: (number | null) | undefined;
        denominator_sum_squares?: (number | null) | undefined;
        key: string;
        number_of_samples: number;
        numerator_denominator_sum_product?: (number | null) | undefined;
        step_counts?: (Array<number> | null) | undefined;
        step_sessions?: (Array<Array<SessionData>> | null) | undefined;
        sum: number;
        sum_squares: number;
        validation_failures?:
            | (Array<ExperimentStatsValidationFailure> | null)
            | undefined;
    };
    export type ExperimentVariantResultFrequentist = {
        confidence_interval?: (Array<number> | null) | undefined;
        covariate_sum?: (number | null) | undefined;
        covariate_sum_product?: (number | null) | undefined;
        covariate_sum_squares?: (number | null) | undefined;
        denominator_sum?: (number | null) | undefined;
        denominator_sum_squares?: (number | null) | undefined;
        key: string;
        method?: string | undefined;
        number_of_samples: number;
        numerator_denominator_sum_product?: (number | null) | undefined;
        p_value?: (number | null) | undefined;
        significant?: (boolean | null) | undefined;
        step_counts?: (Array<number> | null) | undefined;
        step_sessions?: (Array<Array<SessionData>> | null) | undefined;
        sum: number;
        sum_squares: number;
        validation_failures?:
            | (Array<ExperimentStatsValidationFailure> | null)
            | undefined;
    };
    export type ExperimentVariantResultBayesian = {
        chance_to_win?: (number | null) | undefined;
        covariate_sum?: (number | null) | undefined;
        covariate_sum_product?: (number | null) | undefined;
        covariate_sum_squares?: (number | null) | undefined;
        credible_interval?: (Array<number> | null) | undefined;
        denominator_sum?: (number | null) | undefined;
        denominator_sum_squares?: (number | null) | undefined;
        key: string;
        method?: string | undefined;
        number_of_samples: number;
        numerator_denominator_sum_product?: (number | null) | undefined;
        significant?: (boolean | null) | undefined;
        step_counts?: (Array<number> | null) | undefined;
        step_sessions?: (Array<Array<SessionData>> | null) | undefined;
        sum: number;
        sum_squares: number;
        validation_failures?:
            | (Array<ExperimentStatsValidationFailure> | null)
            | undefined;
    };
    export type ExperimentBreakdownResult = {
        /**
         * Control variant stats for this breakdown
         */
        baseline: ExperimentStatsBaseValidated;
        /**
         * The breakdown values as an array (e.g., ["MacOS", "Chrome"] for multi-breakdown, ["Chrome"] for single) Although `BreakdownKeyType` could be an array, we only use the array form for the breakdown_value. The way `BreakdownKeyType` is defined is problematic. It should be treated as a primitive and allow for the types using it to define if it's and array or an optional value.
         */
        breakdown_value: Array<string | number | number>;
        /**
         * Test variant results with statistical comparisons for this breakdown
         */
        variants:
            | Array<ExperimentVariantResultFrequentist>
            | Array<ExperimentVariantResultBayesian>;
    };
    export type ExperimentSignificanceCode =
        | "significant"
        | "not_enough_exposure"
        | "low_win_probability"
        | "high_loss"
        | "high_p_value";
    export type ExperimentVariantTrendsBaseStats = {
        absolute_exposure: number;
        count: number;
        exposure: number;
        key: string;
    };
    export type ExperimentVariantFunnelsBaseStats = {
        failure_count: number;
        key: string;
        success_count: number;
    };
    export type ExperimentQueryResponse = Partial<{
        baseline: ExperimentStatsBaseValidated | null;
        breakdown_results: Array<ExperimentBreakdownResult> | null;
        clickhouse_sql: string | null;
        credible_intervals: Record<string, Array<number>> | null;
        hogql: string | null;
        insight: Array<Record<string, unknown>> | null;
        is_precomputed: boolean | null;
        kind: string;
        metric:
            | (
                  | ExperimentMeanMetric
                  | ExperimentFunnelMetric
                  | ExperimentRatioMetric
                  | ExperimentRetentionMetric
              )
            | null;
        p_value: number | null;
        probability: Record<string, number> | null;
        significance_code: ExperimentSignificanceCode | null;
        significant: boolean | null;
        stats_version: number | null;
        variant_results:
            | Array<ExperimentVariantResultFrequentist>
            | Array<ExperimentVariantResultBayesian>
            | null;
        variants:
            | Array<ExperimentVariantTrendsBaseStats>
            | Array<ExperimentVariantFunnelsBaseStats>
            | null;
        warnings: Array<DataWarehouseSyncWarning> | null;
    }>;
    export type ExperimentQuery = {
        experiment_id?: (number | null) | undefined;
        kind?: string | undefined;
        metric:
            | ExperimentMeanMetric
            | ExperimentFunnelMetric
            | ExperimentRatioMetric
            | ExperimentRetentionMetric;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        name?: (string | null) | undefined;
        precomputation_mode?: (PrecomputationMode | null) | undefined;
        response?: (ExperimentQueryResponse | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ExperimentActorsQuery = {
        exposureConfig?:
            | (ExperimentEventExposureConfig | ActionsNode | null)
            | undefined;
        featureFlagKey?: (string | null) | undefined;
        funnelStep?: (number | null) | undefined;
        funnelStepBreakdown?:
            | (
                  | number
                  | string
                  | number
                  | Array<number | string | number>
                  | null
              )
            | undefined;
        includeRecordings?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        multipleVariantHandling?: (MultipleVariantHandling | null) | undefined;
        response?: (ActorsQueryResponse | null) | undefined;
        source: ExperimentQuery;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type StickinessActorsQuery = {
        compare?: (Compare | null) | undefined;
        day?: (string | number | null) | undefined;
        includeRecordings?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        operator?: (StickinessOperator | null) | undefined;
        response?: (ActorsQueryResponse | null) | undefined;
        series?: (number | null) | undefined;
        source: StickinessQuery;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type PathsV2ElementType =
        | "node"
        | "edge"
        | "dropOff"
        | "other"
        | "chain";
    export type PathsV2ElementSelector = {
        anyStep?: (boolean | null) | undefined;
        chain?: (Array<PathsV2Item> | null) | undefined;
        elementType: PathsV2ElementType;
        item?: (PathsV2Item | null) | undefined;
        source?: (PathsV2Item | null) | undefined;
        stepIndex?: (number | null) | undefined;
        target?: (PathsV2Item | null) | undefined;
    };
    export type PathsV2ActorsQuery = {
        element: PathsV2ElementSelector;
        includeRecordings?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        response?: (ActorsQueryResponse | null) | undefined;
        source: PathsV2Query;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type HogQLFilters = Partial<{
        breakdownFilter: BreakdownFilter | null;
        dateRange: DateRange | null;
        filterTestAccounts: boolean | null;
        interval: IntervalType | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
    }>;
    export type HogQLNotice = {
        end?: (number | null) | undefined;
        fix?: (string | null) | undefined;
        message: string;
        start?: (number | null) | undefined;
    };
    export type PredicateScope = "event" | "person" | "group" | "unknown";
    export type PredicateIndexVerdict =
        | "indexed"
        | "blocked"
        | "unindexed_column"
        | "unindexed_json"
        | "operator_not_indexable";
    export type PredicateIndexUsage = {
        column_name?: (string | null) | undefined;
        end?: (number | null) | undefined;
        fix?: (string | null) | undefined;
        message: string;
        /**
         * HogQL comparison operator, e.g. `==`, `in`, `ilike`.
         */
        operator: string;
        /**
         * Type the value is physically stored as.
         */
        physical_type: string;
        property_name: string;
        scope: PredicateScope;
        /**
         * Type the property definition declares.
         */
        semantic_type: string;
        /**
         * Where the value is physically read from, e.g. `materialized column` or `JSON blob`.
         */
        source_label: string;
        start?: (number | null) | undefined;
        /**
         * Skip indexes this predicate can actually use.
         */
        usable_indexes: Array<string>;
        verdict: PredicateIndexVerdict;
    };
    export type QueryIndexUsage = "undecisive" | "no" | "partial" | "yes";
    export type HogQLMetadataResponse = {
        ch_table_names?: (Array<string> | null) | undefined;
        errors: Array<HogQLNotice>;
        index_usage?: (Array<PredicateIndexUsage> | null) | undefined;
        isUsingIndices?: (QueryIndexUsage | null) | undefined;
        isValid?: (boolean | null) | undefined;
        notices: Array<HogQLNotice>;
        query?: (string | null) | undefined;
        table_names?: (Array<string> | null) | undefined;
        warnings: Array<HogQLNotice>;
    };
    export type HogQLQueryResponse = {
        clickhouse?: (string | null) | undefined;
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        explain?: (Array<string> | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        metadata?: (HogQLMetadataResponse | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query?: (string | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type HogQLVariable = {
        code_name: string;
        isNull?: (boolean | null) | undefined;
        value?: unknown | undefined;
        variableId: string;
    };
    export type HogQLQuery = {
        connectionId?: (string | null) | undefined;
        explain?: (boolean | null) | undefined;
        filters?: (HogQLFilters | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        name?: (string | null) | undefined;
        query: string;
        response?: (HogQLQueryResponse | null) | undefined;
        sendRawQuery?: (boolean | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        values?: (Record<string, unknown> | null) | undefined;
        variables?: (Record<string, HogQLVariable> | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ActorsQuery = Partial<{
        filterTestAccounts: boolean | null;
        fixedProperties: Array<
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | CohortPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
        > | null;
        kind: string;
        limit: number | null;
        modifiers: HogQLQueryModifiers | null;
        offset: number | null;
        orderBy: Array<string> | null;
        properties:
            | Array<
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | CohortPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
              >
            | PropertyGroupFilterValue
            | null;
        response: ActorsQueryResponse | null;
        search: string | null;
        select: Array<string> | null;
        source:
            | InsightActorsQuery
            | FunnelsActorsQuery
            | FunnelCorrelationActorsQuery
            | ExperimentActorsQuery
            | StickinessActorsQuery
            | PathsV2ActorsQuery
            | HogQLQuery
            | null;
        tags: QueryLogTags | null;
        version: number | null;
    }>;
    /**
     * * `first_touch` - First Touch
     * * `last_touch` - Last Touch
     * * `linear` - Linear
     * * `time_decay` - Time Decay
     * * `position_based` - Position Based
     */
    export type AttributionModeEnum =
        | "first_touch"
        | "last_touch"
        | "linear"
        | "time_decay"
        | "position_based";
    /**
     * * `ingest_first_event` - ingest_first_event
     * * `set_up_reverse_proxy` - set_up_reverse_proxy
     * * `create_first_insight` - create_first_insight
     * * `create_first_dashboard` - create_first_dashboard
     * * `track_custom_events` - track_custom_events
     * * `define_actions` - define_actions
     * * `set_up_cohorts` - set_up_cohorts
     * * `explore_trends_insight` - explore_trends_insight
     * * `create_funnel` - create_funnel
     * * `explore_retention_insight` - explore_retention_insight
     * * `explore_paths_insight` - explore_paths_insight
     * * `explore_stickiness_insight` - explore_stickiness_insight
     * * `explore_lifecycle_insight` - explore_lifecycle_insight
     * * `add_authorized_domain` - add_authorized_domain
     * * `set_up_web_vitals` - set_up_web_vitals
     * * `review_web_analytics_dashboard` - review_web_analytics_dashboard
     * * `filter_web_analytics` - filter_web_analytics
     * * `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals
     * * `visit_web_vitals_dashboard` - visit_web_vitals_dashboard
     * * `setup_session_recordings` - setup_session_recordings
     * * `watch_session_recording` - watch_session_recording
     * * `configure_recording_settings` - configure_recording_settings
     * * `create_recording_playlist` - create_recording_playlist
     * * `enable_console_logs` - enable_console_logs
     * * `create_feature_flag` - create_feature_flag
     * * `implement_flag_in_code` - implement_flag_in_code
     * * `update_feature_flag_release_conditions` - update_feature_flag_release_conditions
     * * `create_multivariate_flag` - create_multivariate_flag
     * * `set_up_flag_payloads` - set_up_flag_payloads
     * * `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes
     * * `create_experiment` - create_experiment
     * * `implement_experiment_variants` - implement_experiment_variants
     * * `launch_experiment` - launch_experiment
     * * `review_experiment_results` - review_experiment_results
     * * `create_survey` - create_survey
     * * `launch_survey` - launch_survey
     * * `collect_survey_responses` - collect_survey_responses
     * * `connect_source` - connect_source
     * * `run_first_query` - run_first_query
     * * `join_external_data` - join_external_data
     * * `create_saved_view` - create_saved_view
     * * `enable_error_tracking` - enable_error_tracking
     * * `upload_source_maps` - upload_source_maps
     * * `view_first_error` - view_first_error
     * * `resolve_first_error` - resolve_first_error
     * * `ingest_first_llm_event` - ingest_first_llm_event
     * * `view_first_trace` - view_first_trace
     * * `track_costs` - track_costs
     * * `set_up_llm_evaluation` - set_up_llm_evaluation
     * * `run_ai_playground` - run_ai_playground
     * * `enable_log_capture` - enable_log_capture
     * * `view_first_logs` - view_first_logs
     * * `create_first_workflow` - create_first_workflow
     * * `set_up_first_workflow_channel` - set_up_first_workflow_channel
     * * `configure_workflow_trigger` - configure_workflow_trigger
     * * `add_workflow_action` - add_workflow_action
     * * `launch_workflow` - launch_workflow
     * * `create_first_endpoint` - create_first_endpoint
     * * `configure_endpoint` - configure_endpoint
     * * `test_endpoint` - test_endpoint
     * * `create_early_access_feature` - create_early_access_feature
     * * `update_feature_stage` - update_feature_stage
     * * `use_posthog_ai` - use_posthog_ai
     * * `use_posthog_code` - use_posthog_code
     * * `use_posthog_mcp` - use_posthog_mcp
     * * `use_posthog_in_slack` - use_posthog_in_slack
     */
    export type AvailableSetupTaskIdsEnum =
        | "ingest_first_event"
        | "set_up_reverse_proxy"
        | "create_first_insight"
        | "create_first_dashboard"
        | "track_custom_events"
        | "define_actions"
        | "set_up_cohorts"
        | "explore_trends_insight"
        | "create_funnel"
        | "explore_retention_insight"
        | "explore_paths_insight"
        | "explore_stickiness_insight"
        | "explore_lifecycle_insight"
        | "add_authorized_domain"
        | "set_up_web_vitals"
        | "review_web_analytics_dashboard"
        | "filter_web_analytics"
        | "set_up_web_analytics_conversion_goals"
        | "visit_web_vitals_dashboard"
        | "setup_session_recordings"
        | "watch_session_recording"
        | "configure_recording_settings"
        | "create_recording_playlist"
        | "enable_console_logs"
        | "create_feature_flag"
        | "implement_flag_in_code"
        | "update_feature_flag_release_conditions"
        | "create_multivariate_flag"
        | "set_up_flag_payloads"
        | "set_up_flag_evaluation_runtimes"
        | "create_experiment"
        | "implement_experiment_variants"
        | "launch_experiment"
        | "review_experiment_results"
        | "create_survey"
        | "launch_survey"
        | "collect_survey_responses"
        | "connect_source"
        | "run_first_query"
        | "join_external_data"
        | "create_saved_view"
        | "enable_error_tracking"
        | "upload_source_maps"
        | "view_first_error"
        | "resolve_first_error"
        | "ingest_first_llm_event"
        | "view_first_trace"
        | "track_costs"
        | "set_up_llm_evaluation"
        | "run_ai_playground"
        | "enable_log_capture"
        | "view_first_logs"
        | "create_first_workflow"
        | "set_up_first_workflow_channel"
        | "configure_workflow_trigger"
        | "add_workflow_action"
        | "launch_workflow"
        | "create_first_endpoint"
        | "configure_endpoint"
        | "test_endpoint"
        | "create_early_access_feature"
        | "update_feature_stage"
        | "use_posthog_ai"
        | "use_posthog_code"
        | "use_posthog_mcp"
        | "use_posthog_in_slack";
    /**
     * * `AED` - AED
     * * `AFN` - AFN
     * * `ALL` - ALL
     * * `AMD` - AMD
     * * `ANG` - ANG
     * * `AOA` - AOA
     * * `ARS` - ARS
     * * `AUD` - AUD
     * * `AWG` - AWG
     * * `AZN` - AZN
     * * `BAM` - BAM
     * * `BBD` - BBD
     * * `BDT` - BDT
     * * `BGN` - BGN
     * * `BHD` - BHD
     * * `BIF` - BIF
     * * `BMD` - BMD
     * * `BND` - BND
     * * `BOB` - BOB
     * * `BRL` - BRL
     * * `BSD` - BSD
     * * `BTC` - BTC
     * * `BTN` - BTN
     * * `BWP` - BWP
     * * `BYN` - BYN
     * * `BZD` - BZD
     * * `CAD` - CAD
     * * `CDF` - CDF
     * * `CHF` - CHF
     * * `CLP` - CLP
     * * `CNY` - CNY
     * * `COP` - COP
     * * `CRC` - CRC
     * * `CVE` - CVE
     * * `CZK` - CZK
     * * `DJF` - DJF
     * * `DKK` - DKK
     * * `DOP` - DOP
     * * `DZD` - DZD
     * * `EGP` - EGP
     * * `ERN` - ERN
     * * `ETB` - ETB
     * * `EUR` - EUR
     * * `FJD` - FJD
     * * `GBP` - GBP
     * * `GEL` - GEL
     * * `GHS` - GHS
     * * `GIP` - GIP
     * * `GMD` - GMD
     * * `GNF` - GNF
     * * `GTQ` - GTQ
     * * `GYD` - GYD
     * * `HKD` - HKD
     * * `HNL` - HNL
     * * `HRK` - HRK
     * * `HTG` - HTG
     * * `HUF` - HUF
     * * `IDR` - IDR
     * * `ILS` - ILS
     * * `INR` - INR
     * * `IQD` - IQD
     * * `IRR` - IRR
     * * `ISK` - ISK
     * * `JMD` - JMD
     * * `JOD` - JOD
     * * `JPY` - JPY
     * * `KES` - KES
     * * `KGS` - KGS
     * * `KHR` - KHR
     * * `KMF` - KMF
     * * `KRW` - KRW
     * * `KWD` - KWD
     * * `KYD` - KYD
     * * `KZT` - KZT
     * * `LAK` - LAK
     * * `LBP` - LBP
     * * `LKR` - LKR
     * * `LRD` - LRD
     * * `LTL` - LTL
     * * `LVL` - LVL
     * * `LSL` - LSL
     * * `LYD` - LYD
     * * `MAD` - MAD
     * * `MDL` - MDL
     * * `MGA` - MGA
     * * `MKD` - MKD
     * * `MMK` - MMK
     * * `MNT` - MNT
     * * `MOP` - MOP
     * * `MRU` - MRU
     * * `MTL` - MTL
     * * `MUR` - MUR
     * * `MVR` - MVR
     * * `MWK` - MWK
     * * `MXN` - MXN
     * * `MYR` - MYR
     * * `MZN` - MZN
     * * `NAD` - NAD
     * * `NGN` - NGN
     * * `NIO` - NIO
     * * `NOK` - NOK
     * * `NPR` - NPR
     * * `NZD` - NZD
     * * `OMR` - OMR
     * * `PAB` - PAB
     * * `PEN` - PEN
     * * `PGK` - PGK
     * * `PHP` - PHP
     * * `PKR` - PKR
     * * `PLN` - PLN
     * * `PYG` - PYG
     * * `QAR` - QAR
     * * `RON` - RON
     * * `RSD` - RSD
     * * `RUB` - RUB
     * * `RWF` - RWF
     * * `SAR` - SAR
     * * `SBD` - SBD
     * * `SCR` - SCR
     * * `SDG` - SDG
     * * `SEK` - SEK
     * * `SGD` - SGD
     * * `SRD` - SRD
     * * `SSP` - SSP
     * * `STN` - STN
     * * `SYP` - SYP
     * * `SZL` - SZL
     * * `THB` - THB
     * * `TJS` - TJS
     * * `TMT` - TMT
     * * `TND` - TND
     * * `TOP` - TOP
     * * `TRY` - TRY
     * * `TTD` - TTD
     * * `TWD` - TWD
     * * `TZS` - TZS
     * * `UAH` - UAH
     * * `UGX` - UGX
     * * `USD` - USD
     * * `UYU` - UYU
     * * `UZS` - UZS
     * * `VES` - VES
     * * `VND` - VND
     * * `VUV` - VUV
     * * `WST` - WST
     * * `XAF` - XAF
     * * `XCD` - XCD
     * * `XOF` - XOF
     * * `XPF` - XPF
     * * `YER` - YER
     * * `ZAR` - ZAR
     * * `ZMW` - ZMW
     */
    export type BaseCurrencyEnum =
        | "AED"
        | "AFN"
        | "ALL"
        | "AMD"
        | "ANG"
        | "AOA"
        | "ARS"
        | "AUD"
        | "AWG"
        | "AZN"
        | "BAM"
        | "BBD"
        | "BDT"
        | "BGN"
        | "BHD"
        | "BIF"
        | "BMD"
        | "BND"
        | "BOB"
        | "BRL"
        | "BSD"
        | "BTC"
        | "BTN"
        | "BWP"
        | "BYN"
        | "BZD"
        | "CAD"
        | "CDF"
        | "CHF"
        | "CLP"
        | "CNY"
        | "COP"
        | "CRC"
        | "CVE"
        | "CZK"
        | "DJF"
        | "DKK"
        | "DOP"
        | "DZD"
        | "EGP"
        | "ERN"
        | "ETB"
        | "EUR"
        | "FJD"
        | "GBP"
        | "GEL"
        | "GHS"
        | "GIP"
        | "GMD"
        | "GNF"
        | "GTQ"
        | "GYD"
        | "HKD"
        | "HNL"
        | "HRK"
        | "HTG"
        | "HUF"
        | "IDR"
        | "ILS"
        | "INR"
        | "IQD"
        | "IRR"
        | "ISK"
        | "JMD"
        | "JOD"
        | "JPY"
        | "KES"
        | "KGS"
        | "KHR"
        | "KMF"
        | "KRW"
        | "KWD"
        | "KYD"
        | "KZT"
        | "LAK"
        | "LBP"
        | "LKR"
        | "LRD"
        | "LTL"
        | "LVL"
        | "LSL"
        | "LYD"
        | "MAD"
        | "MDL"
        | "MGA"
        | "MKD"
        | "MMK"
        | "MNT"
        | "MOP"
        | "MRU"
        | "MTL"
        | "MUR"
        | "MVR"
        | "MWK"
        | "MXN"
        | "MYR"
        | "MZN"
        | "NAD"
        | "NGN"
        | "NIO"
        | "NOK"
        | "NPR"
        | "NZD"
        | "OMR"
        | "PAB"
        | "PEN"
        | "PGK"
        | "PHP"
        | "PKR"
        | "PLN"
        | "PYG"
        | "QAR"
        | "RON"
        | "RSD"
        | "RUB"
        | "RWF"
        | "SAR"
        | "SBD"
        | "SCR"
        | "SDG"
        | "SEK"
        | "SGD"
        | "SRD"
        | "SSP"
        | "STN"
        | "SYP"
        | "SZL"
        | "THB"
        | "TJS"
        | "TMT"
        | "TND"
        | "TOP"
        | "TRY"
        | "TTD"
        | "TWD"
        | "TZS"
        | "UAH"
        | "UGX"
        | "USD"
        | "UYU"
        | "UZS"
        | "VES"
        | "VND"
        | "VUV"
        | "WST"
        | "XAF"
        | "XCD"
        | "XOF"
        | "XPF"
        | "YER"
        | "ZAR"
        | "ZMW";
    export type EventPropFilterTypeEnum = "event" | "element";
    export type EventPropFilter = {
        type: EventPropFilterTypeEnum;
        key: string;
        value: unknown;
        operator?: (string | null) | undefined;
    };
    export type HogQLFilter = {
        type: string;
        key: string;
        value?: unknown | undefined;
    };
    export type BehavioralFilter = {
        bytecode?: (Array<unknown> | null) | undefined;
        bytecode_error?: (string | null) | undefined;
        conditionHash?: (string | null) | undefined;
        type: string;
        key: string | number;
        value: string;
        event_type: string;
        time_value?: (number | null) | undefined;
        time_interval?: (string | null) | undefined;
        negation?: boolean | undefined;
        operator?: (string | null) | undefined;
        operator_value?: (number | null) | undefined;
        seq_time_interval?: (string | null) | undefined;
        seq_time_value?: (number | null) | undefined;
        seq_event?: (string | number | null) | undefined;
        seq_event_type?: (string | null) | undefined;
        total_periods?: (number | null) | undefined;
        min_periods?: (number | null) | undefined;
        event_filters?:
            | (Array<EventPropFilter | HogQLFilter> | null)
            | undefined;
        explicit_datetime?: (string | null) | undefined;
        explicit_datetime_to?: (string | null) | undefined;
    };
    export type BiasRisk = {
        /**
         * Observed share of users assigned to `$multiple`, as a percentage (0-100).
         */
        multiple_variant_percentage: number;
    };
    export type BoxPlotSettings = Partial<{
        excludeOutliers: boolean | null;
        maxColumn: string | null;
        meanColumn: string | null;
        medianColumn: string | null;
        minColumn: string | null;
        p25Column: string | null;
        p75Column: string | null;
        seriesColumn: string | null;
        xAxisColumn: string | null;
    }>;
    /**
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID
     */
    export type BucketingIdentifierEnum = "distinct_id" | "device_id";
    /**
     * * `zip` - zip
     */
    export type BundleFormatEnum = "zip";
    /**
     * * `b2b` - B2B
     * * `b2c` - B2C
     * * `other` - Other
     */
    export type BusinessModelEnum = "b2b" | "b2c" | "other";
    export type MatchField = "campaign_name" | "campaign_id";
    export type CampaignFieldPreference = { match_field: MatchField };
    /**
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both
     */
    export type CdcTableModeEnum = "consolidated" | "cdc_only" | "both";
    /**
     * * `slack_channel_message` - Channel message
     * * `slack_bot_mention` - Bot mention
     * * `slack_emoji_reaction` - Emoji reaction
     * * `teams_channel_message` - Teams channel message
     * * `teams_bot_mention` - Teams bot mention
     * * `widget_embedded` - Widget
     * * `widget_api` - API
     * * `github_issue` - GitHub issue
     */
    export type ChannelDetailEnum =
        | "slack_channel_message"
        | "slack_bot_mention"
        | "slack_emoji_reaction"
        | "teams_channel_message"
        | "teams_bot_mention"
        | "widget_embedded"
        | "widget_api"
        | "github_issue";
    /**
     * * `widget` - Widget
     * * `email` - Email
     * * `slack` - Slack
     * * `teams` - Microsoft Teams
     * * `github` - GitHub
     */
    export type ChannelEnum = "widget" | "email" | "slack" | "teams" | "github";
    export type DisplayType = "auto" | "line" | "bar" | "area";
    export type YAxisPosition = "left" | "right";
    export type ChartSettingsDisplay = Partial<{
        color: string | null;
        displayType: DisplayType | null;
        label: string | null;
        trendLine: boolean | null;
        yAxisPosition: YAxisPosition | null;
    }>;
    export type Style = "none" | "number" | "short" | "percent";
    export type ChartSettingsFormatting = Partial<{
        decimalPlaces: number | null;
        prefix: string | null;
        style: Style | null;
        suffix: string | null;
    }>;
    export type Settings = Partial<{
        display: ChartSettingsDisplay | null;
        formatting: ChartSettingsFormatting | null;
    }>;
    export type ChartAxis = {
        column: string;
        settings?: (Settings | null) | undefined;
    };
    export type HeatmapGradientStop = { color: string; value: number };
    export type GradientScaleMode = "absolute" | "relative";
    export type HeatmapSortOrder = "asc" | "desc";
    export type HeatmapSettings = Partial<{
        gradient: Array<HeatmapGradientStop> | null;
        gradientPreset: string | null;
        gradientScaleMode: GradientScaleMode | null;
        nullLabel: string | null;
        nullValue: string | null;
        sortColumn: string | null;
        sortOrder: HeatmapSortOrder | null;
        valueColumn: string | null;
        xAxisColumn: string | null;
        xAxisLabel: string | null;
        yAxisColumn: string | null;
        yAxisLabel: string | null;
    }>;
    export type Scale = "linear" | "logarithmic";
    export type YAxisSettings = Partial<{
        label: string | null;
        scale: Scale | null;
        showGridLines: boolean | null;
        showTicks: boolean | null;
        startAtZero: boolean | null;
    }>;
    export type SliceContent = "labels" | "values" | "none";
    export type ValueDisplay = "absolute" | "percentage";
    export type PieChartSettings = Partial<{
        showTotal: boolean | null;
        sliceContent: SliceContent | null;
        valueDisplay: ValueDisplay | null;
    }>;
    export type XScale = "linear" | "logarithmic";
    export type ScatterChartSettings = Partial<{
        showBestFit: boolean | null;
        xScale: XScale | null;
        xStartAtZero: boolean | null;
    }>;
    export type ChartSettings = Partial<{
        boxPlot: BoxPlotSettings | null;
        chartStyle: ChartStyle | null;
        goalLines: Array<GoalLine> | null;
        heatmap: HeatmapSettings | null;
        leftYAxisSettings: YAxisSettings | null;
        legendPosition: LegendPosition | null;
        pie: PieChartSettings | null;
        resultCustomizations: Record<string, ResultCustomizationByValue> | null;
        rightYAxisSettings: YAxisSettings | null;
        scatter: ScatterChartSettings | null;
        seriesBreakdownColumn: string | null;
        showAnnotations: boolean | null;
        showLegend: boolean | null;
        showNullsAsZero: boolean | null;
        showPieTotal: boolean | null;
        showTotalRow: boolean | null;
        showValuesOnSeries: boolean | null;
        showXAxisBorder: boolean | null;
        showXAxisTicks: boolean | null;
        showYAxisBorder: boolean | null;
        stackBars100: boolean | null;
        xAxis: ChartAxis | null;
        xAxisLabel: string | null;
        yAxis: Array<ChartAxis> | null;
        yAxisAtZero: boolean | null;
    }>;
    /**
     * * `claude` - claude
     */
    export type ClaudeRuntimeAdapterEnum = "claude";
    /**
     * * `interactive` - interactive
     * * `background` - background
     */
    export type TaskExecutionModeEnum = "interactive" | "background";
    /**
     * * `user` - user
     * * `bot` - bot
     */
    export type PrAuthorshipModeEnum = "user" | "bot";
    /**
     * * `manual` - manual
     * * `signal_report` - signal_report
     */
    export type RunSourceEnum = "manual" | "signal_report";
    /**
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode
     */
    export type ReasoningEffortEnum =
        | "low"
        | "medium"
        | "high"
        | "xhigh"
        | "max"
        | "ultracode";
    /**
     * * `200k` - 200k
     * * `1m` - 1m
     */
    export type ContextWindowEnum = "200k" | "1m";
    /**
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     */
    export type InitialPermissionModeEnum =
        | "default"
        | "acceptEdits"
        | "plan"
        | "bypassPermissions"
        | "auto";
    /**
     * Request body for creating a new task run
     */
    export type ClaudeTaskRunCreateSchema = {
        /**
         * Request body for creating a new task run
         */
        imported_mcp_servers?: (Array<ImportedMcpServer> | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        relayed_mcp_servers?: (Array<RelayedMcpServer> | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        mode?: (TaskExecutionModeEnum & unknown) | undefined;
        /**
         * Request body for creating a new task run
         */
        branch?: (string | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        resume_from_run_id?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        pending_user_message?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        pending_user_artifact_ids?: Array<string> | undefined;
        /**
         * Request body for creating a new task run
         */
        sandbox_environment_id?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        custom_image_id?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        pr_authorship_mode?: PrAuthorshipModeEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        auto_publish?: (boolean | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        run_source?: RunSourceEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        signal_report_id?: string | undefined;
        /**
         * Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.
         *
         * * `claude` - claude
         */
        runtime_adapter: ClaudeRuntimeAdapterEnum;
        /**
         * LLM model identifier to run in the Claude runtime.
         */
        model: string;
        /**
         * Request body for creating a new task run
         */
        reasoning_effort?: ReasoningEffortEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        context_window?: ContextWindowEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        fast_mode?: (boolean | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        github_user_token?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        initial_permission_mode?: InitialPermissionModeEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        rtk_enabled?: (boolean | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        benjamin_enabled?: (boolean | null) | undefined;
    };
    /**
     * * `codex` - codex
     */
    export type CodexRuntimeAdapterEnum = "codex";
    /**
     * * `plan` - plan
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access
     */
    export type CodexTaskRunCreateSchemaInitialPermissionModeEnum =
        | "plan"
        | "auto"
        | "read-only"
        | "full-access";
    /**
     * Request body for creating a new task run
     */
    export type CodexTaskRunCreateSchema = {
        /**
         * Request body for creating a new task run
         */
        imported_mcp_servers?: (Array<ImportedMcpServer> | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        relayed_mcp_servers?: (Array<RelayedMcpServer> | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        mode?: (TaskExecutionModeEnum & unknown) | undefined;
        /**
         * Request body for creating a new task run
         */
        branch?: (string | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        resume_from_run_id?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        pending_user_message?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        pending_user_artifact_ids?: Array<string> | undefined;
        /**
         * Request body for creating a new task run
         */
        sandbox_environment_id?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        custom_image_id?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        pr_authorship_mode?: PrAuthorshipModeEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        auto_publish?: (boolean | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        run_source?: RunSourceEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        signal_report_id?: string | undefined;
        /**
         * Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.
         *
         * * `codex` - codex
         */
        runtime_adapter: CodexRuntimeAdapterEnum;
        /**
         * LLM model identifier to run in the Codex runtime.
         */
        model: string;
        /**
         * Request body for creating a new task run
         */
        reasoning_effort?: ReasoningEffortEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        context_window?: ContextWindowEnum | undefined;
        /**
         * Request body for creating a new task run
         */
        fast_mode?: (boolean | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        github_user_token?: string | undefined;
        /**
         * Request body for creating a new task run
         */
        initial_permission_mode?:
            | CodexTaskRunCreateSchemaInitialPermissionModeEnum
            | undefined;
        /**
         * Request body for creating a new task run
         */
        rtk_enabled?: (boolean | null) | undefined;
        /**
         * Request body for creating a new task run
         */
        benjamin_enabled?: (boolean | null) | undefined;
    };
    export type PropertyGroupOperatorEnum = "AND" | "OR";
    export type CohortFilter = {
        bytecode?: (Array<unknown> | null) | undefined;
        bytecode_error?: (string | null) | undefined;
        conditionHash?: (string | null) | undefined;
        type: string;
        key: string;
        value: number;
        negation?: boolean | undefined;
    };
    export type PersonFilter = {
        operator?: (string | null) | undefined;
        value?: unknown | undefined;
        bytecode?: (Array<unknown> | null) | undefined;
        bytecode_error?: (string | null) | undefined;
        conditionHash?: (string | null) | undefined;
        type: string;
        key: string;
        negation?: boolean | undefined;
    };
    /**
     * Filter on a top-level persons-table column (e.g. created_at) rather than the
     * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
     */
    export type PersonMetadataFilter = {
        /**
         * Filter on a top-level persons-table column (e.g. created_at) rather than the
         * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
         */
        operator?: (string | null) | undefined;
        /**
         * Filter on a top-level persons-table column (e.g. created_at) rather than the
         * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
         */
        value?: unknown | undefined;
        /**
         * Filter on a top-level persons-table column (e.g. created_at) rather than the
         * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
         */
        bytecode?: (Array<unknown> | null) | undefined;
        /**
         * Filter on a top-level persons-table column (e.g. created_at) rather than the
         * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
         */
        bytecode_error?: (string | null) | undefined;
        /**
         * Filter on a top-level persons-table column (e.g. created_at) rather than the
         * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
         */
        conditionHash?: (string | null) | undefined;
        type: string;
        key: string;
        /**
         * Filter on a top-level persons-table column (e.g. created_at) rather than the
         * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
         */
        negation?: boolean | undefined;
    };
    /**
     * AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.
     */
    export type CohortFilterGroup = {
        type: PropertyGroupOperatorEnum;
        values: Array<
            | BehavioralFilter
            | CohortFilter
            | PersonFilter
            | PersonMetadataFilter
            | CohortFilterGroup
        >;
    };
    export type CohortFilters = {
        properties: CohortFilterGroup;
        filterTestAccounts?: (boolean | null) | undefined;
    };
    /**
     * * `static` - static
     * * `person_property` - person_property
     * * `behavioral` - behavioral
     * * `realtime` - realtime
     * * `analytical` - analytical
     */
    export type CohortTypeEnum =
        | "static"
        | "person_property"
        | "behavioral"
        | "realtime"
        | "analytical";
    export type CohortConditionTypeFlags = {
        /**
         * The filters include a person property or person_metadata condition.
         */
        person_properties: boolean;
        /**
         * The filters include a behavioral condition that is not lifecycle-style (e.g. performed_event, performed_event_multiple, performed_event_sequence, or their negations).
         */
        behavioral: boolean;
        /**
         * The filters include a lifecycle-style behavioral condition (first-seen/regularly/stopped/restarted performing an event).
         */
        lifecycle: boolean;
        /**
         * The filters include a nested reference to another cohort.
         */
        cohorts: boolean;
    };
    export type SearchMatchTypeEnum = "exact" | "similar";
    export type Cohort = {
        id: number;
        name?: (string | null) | undefined;
        description?: string | undefined;
        groups?: unknown | undefined;
        deleted?: boolean | undefined;
        filters?: (CohortFilters | null) | undefined;
        query?: unknown | undefined;
        version: number | null;
        pending_version: number | null;
        is_calculating: boolean;
        created_by: UserBasic & unknown;
        created_at: string | null;
        last_calculation: string | null;
        last_backfill_person_properties_at: string | null;
        errors_calculating: number;
        last_error_message: string | null;
        count: number | null;
        /**
         * Number of IDs supplied by the most recent static cohort import. Null if the cohort was never populated from a list of IDs.
         */
        last_import_total_count: number | null;
        /**
         * How many of the IDs in the most recent static cohort import matched no person, and so were not added to the cohort.
         */
        last_import_unmatched_count: number | null;
        is_static?: boolean | undefined;
        cohort_type?: (CohortTypeEnum | BlankEnum | NullEnum) | undefined;
        /**
         * Flags describing which kinds of conditions the cohort's filters contain. Null when the cohort has no filters to classify.
         */
        condition_type: CohortConditionTypeFlags | null;
        experiment_set: Array<number>;
        /**
         * How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.
         */
        search_match_type: SearchMatchTypeEnum | NullEnum;
        _create_in_folder?: string | undefined;
        _create_static_person_ids?: Array<string> | undefined;
    };
    export type ColorMode = "light" | "dark";
    export type CommentSlackThreadRef = {
        /**
         * Slack channel ID this discussion is mirrored to.
         */
        channel_id: string;
        /**
         * Slack channel name resolved from Slack when the discussion was sent (no leading #). Empty for private channels and when unknown; may lag behind a rename in Slack.
         */
        channel_name: string;
        /**
         * Deep link that opens the mirrored Slack thread.
         */
        url: string;
    };
    export type Comment = {
        id: string;
        created_by: UserBasic | null;
        scope?: string | undefined;
        item_context?: unknown | undefined;
        deleted?: (boolean | null) | undefined;
        mentions?: Array<number> | undefined;
        slug?: string | undefined;
        is_task?: boolean | undefined;
        /**
         * The user who marked this task complete. Null for open tasks and non-task comments.
         */
        completed_by: UserBasic | null;
        /**
         * The Slack thread this comment's discussion is mirrored to, or null. Set only on a tracked thread-root comment; used to surface an 'Open in Slack' link and hide re-sending.
         */
        slack_thread: CommentSlackThreadRef | null;
        content?: (string | null) | undefined;
        rich_content?: unknown | undefined;
        version: number;
        created_at: string;
        item_id?: (string | null) | undefined;
        /**
         * ISO timestamp when the task was marked complete. Only meaningful when is_task is true. Read-only — toggled via the /complete and /reopen actions, not via PATCH.
         */
        completed_at: string | null;
        source_comment?: (string | null) | undefined;
    };
    export type CommentError = {
        /**
         * Human-readable explanation of what went wrong.
         */
        detail: string;
        error_type?: string | undefined;
    };
    /**
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid
     */
    export type ConclusionEnum =
        | "won"
        | "lost"
        | "inconclusive"
        | "stopped_early"
        | "invalid";
    export type ConditionalFormattingRule = {
        bytecode: Array<unknown>;
        color: string;
        colorMode?: (ColorMode | null) | undefined;
        columnName: string;
        id: string;
        input: string;
        templateId: string;
    };
    export type ConversionGoalFilter1 = {
        conversion_goal_id: string;
        conversion_goal_name: string;
        counts_as_customer?: (boolean | null) | undefined;
        counts_as_revenue?: (boolean | null) | undefined;
        custom_name?: (string | null) | undefined;
        event?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        orderBy?: (Array<string> | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        schema_map: Record<string, string | unknown>;
        version?: (number | null) | undefined;
    };
    export type ConversionGoalFilter2 = {
        conversion_goal_id: string;
        conversion_goal_name: string;
        counts_as_customer?: (boolean | null) | undefined;
        counts_as_revenue?: (boolean | null) | undefined;
        custom_name?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        id: number;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        schema_map: Record<string, string | unknown>;
        version?: (number | null) | undefined;
    };
    export type ConversionGoalFilter3 = {
        conversion_goal_id: string;
        conversion_goal_name: string;
        counts_as_customer?: (boolean | null) | undefined;
        counts_as_revenue?: (boolean | null) | undefined;
        custom_name?: (string | null) | undefined;
        distinct_id_field: string;
        dw_source_type?: (string | null) | undefined;
        fixedProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        id: string;
        id_field: string;
        kind?: string | undefined;
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_multiplier?: (number | null) | undefined;
        math_property?: (string | null) | undefined;
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        math_property_type?: (string | null) | undefined;
        name?: (string | null) | undefined;
        optionalInFunnel?: (boolean | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (Record<string, unknown> | null) | undefined;
        schema_map: Record<string, string | unknown>;
        table_name: string;
        timestamp_field: string;
        version?: (number | null) | undefined;
    };
    export type ConversionRateInputType = "manual" | "automatic";
    /**
     * * `0` - Disabled
     * * `1` - Stateless
     * * `2` - Stateful
     */
    export type CookielessServerHashModeEnum = 0 | 1 | 2;
    /**
     * * `default` - Default
     * * `template` - Template
     * * `duplicate` - Duplicate
     * * `unlisted` - Unlisted (product-embedded)
     */
    export type DashboardCreationModeEnum =
        | "default"
        | "template"
        | "duplicate"
        | "unlisted";
    /**
     * * `21` - Everyone in the project can edit
     * * `37` - Only those invited to this dashboard can edit
     */
    export type RestrictionLevelEnum = 21 | 37;
    /**
     * * `21` - Can view dashboard
     * * `37` - Can edit dashboard
     */
    export type PrivilegeLevelEnum = 21 | 37;
    /**
     * * `tight` - tight
     * * `condensed` - condensed
     * * `standard` - standard
     * * `relaxed` - relaxed
     * * `wide` - wide
     */
    export type TileSpacingEnum =
        | "tight"
        | "condensed"
        | "standard"
        | "relaxed"
        | "wide";
    /**
     * * `vertical` - vertical
     * * `horizontal` - horizontal
     * * `stable` - stable
     */
    export type LayoutCompactionEnum = "vertical" | "horizontal" | "stable";
    export type DashboardCustomization = Partial<{
        tile_spacing: TileSpacingEnum;
        layout_compaction: LayoutCompactionEnum;
    }>;
    /**
     * Serializer mixin that handles tags for objects.
     */
    export type Dashboard = {
        id: number;
        /**
         * Serializer mixin that handles tags for objects.
         */
        name?: (string | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        description?: string | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        pinned?: boolean | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        /**
         * Serializer mixin that handles tags for objects.
         */
        last_accessed_at?: (string | null) | undefined;
        last_viewed_at: string | null;
        /**
         * Path of the project-tree folder this dashboard is filed under in the file system, e.g. 'Unfiled/Dashboards'. An empty string means the project root; null means the dashboard has no file system entry. The dashboard's own name is not part of the path.
         */
        folder: string | null;
        /**
         * Id of this dashboard's file system entry, or null when it has none. Together with `file_system_path` this is everything a caller needs to move the dashboard between folders, so a list page does not have to look the entry up separately.
         */
        file_system_id: string | null;
        /**
         * Full path of this dashboard's file system entry, e.g. 'Unfiled/Dashboards/Revenue'. Unlike `folder` this keeps the dashboard's own name as the last segment, which is what a move needs in order to compute the destination path. Null when it has no entry.
         */
        file_system_path: string | null;
        is_shared: boolean;
        /**
         * Serializer mixin that handles tags for objects.
         */
        deleted?: boolean | undefined;
        creation_mode: DashboardCreationModeEnum & unknown;
        filters: Record<string, unknown>;
        variables: Record<string, unknown> | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        breakdown_colors?: unknown | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        data_color_theme_id?: (number | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        tags?: Array<unknown> | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        restriction_level?: RestrictionLevelEnum | undefined;
        effective_restriction_level: RestrictionLevelEnum & unknown;
        effective_privilege_level: PrivilegeLevelEnum & unknown;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        access_control_version: string;
        /**
         * Serializer mixin that handles tags for objects.
         */
        last_refresh?: (string | null) | undefined;
        persisted_filters: Record<string, unknown> | null;
        persisted_variables: Record<string, unknown> | null;
        team_id: number;
        /**
         * Serializer mixin that handles tags for objects.
         */
        quick_filter_ids?: (Array<string> | null) | undefined;
        /**
         * Dashboard display settings.
         */
        customization: DashboardCustomization & unknown;
        /**
         * Serializer mixin that handles tags for objects.
         */
        grid_spacing?: (TileSpacingEnum & unknown) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        layout_compaction?: (LayoutCompactionEnum & unknown) | undefined;
        tiles: Array<Record<string, unknown>> | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        use_template?: string | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        use_dashboard?: (number | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        delete_insights?: boolean | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        _create_in_folder?: string | undefined;
    };
    export type DashboardFilter = Partial<{
        breakdown_filter: BreakdownFilter | null;
        date_from: string | null;
        date_to: string | null;
        explicitDate: boolean | null;
        filterTestAccounts: boolean | null;
        interval: IntervalType | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
    }>;
    /**
     * OpenAPI-only shape for a dashboard's filters object (agents/MCP).
     *
     * Documents the dashboard-level filters that act as the single source of truth for the
     * dashboard's tiles. Runtime persistence reads the raw ``filters`` dict from the request body, so
     * extra keys are accepted, but these are the ones agents should set.
     */
    export type DashboardFiltersOpenApi = Partial<{
        date_from: string | null;
        date_to: string | null;
        properties: unknown;
    }>;
    /**
     * * `activity_events_list` - activity_events_list
     * * `conversations_recent_tickets` - conversations_recent_tickets
     * * `error_tracking_list` - error_tracking_list
     * * `experiment_results` - experiment_results
     * * `experiments_list` - experiments_list
     * * `logs_list` - logs_list
     * * `session_replay_list` - session_replay_list
     * * `survey_results` - survey_results
     */
    export type DashboardPatchWidgetOpenApiWidgetTypeEnum =
        | "activity_events_list"
        | "conversations_recent_tickets"
        | "error_tracking_list"
        | "experiment_results"
        | "experiments_list"
        | "logs_list"
        | "session_replay_list"
        | "survey_results";
    export type WidgetDateRange = Partial<{
        date_from:
            | (
                  | "-1M"
                  | "-30M"
                  | "-1h"
                  | "-3h"
                  | "-24h"
                  | "-7d"
                  | "-14d"
                  | "-30d"
                  | "-90d"
              )
            | null;
    }>;
    export type WidgetFilterEntry = {
        filterId: string;
        propertyName: string;
        optionId: string;
        operator: PropertyOperator;
        value?: (string | Array<string> | null) | undefined;
    };
    export type ActivityEventsPropertyFilter = {
        key: string;
        label?: (string | null) | undefined;
        operator: PropertyOperator;
        type: "event" | "person";
        value?:
            | (
                  | Array<string | number | boolean>
                  | string
                  | number
                  | boolean
                  | null
              )
            | undefined;
    };
    export type ActivityEventsListWidgetConfig = Partial<{
        dateRange: WidgetDateRange | null;
        filterTestAccounts: boolean | null;
        widgetFilters: Record<string, WidgetFilterEntry> | null;
        limit: number;
        eventName: string | null;
        properties: Array<ActivityEventsPropertyFilter> | null;
    }>;
    export type WidgetAssigneeFilter = {
        id: string | number;
        type: "user" | "role";
    };
    export type ErrorTrackingListWidgetConfig = Partial<{
        dateRange: WidgetDateRange | null;
        filterTestAccounts: boolean | null;
        widgetFilters: Record<string, WidgetFilterEntry> | null;
        limit: number;
        orderBy:
            | "last_seen"
            | "first_seen"
            | "occurrences"
            | "users"
            | "sessions";
        orderDirection: "ASC" | "DESC";
        status:
            | "archived"
            | "active"
            | "resolved"
            | "pending_release"
            | "suppressed"
            | "all";
        assignee: WidgetAssigneeFilter | null;
    }>;
    export type SessionReplayListWidgetConfig = Partial<{
        dateRange: WidgetDateRange | null;
        filterTestAccounts: boolean | null;
        widgetFilters: Record<string, WidgetFilterEntry> | null;
        limit: number;
        orderBy:
            | "start_time"
            | "activity_score"
            | "recording_duration"
            | "duration"
            | "click_count"
            | "console_error_count";
        orderDirection: "ASC" | "DESC";
        savedFilterId: string | null;
        collectionId: string | null;
    }>;
    export type ExperimentsListWidgetConfig = Partial<{
        limit: number;
        orderBy: "created_at" | "name" | "start_date";
        orderDirection: "ASC" | "DESC";
        status:
            | "draft"
            | "running"
            | "paused"
            | "exposure_frozen"
            | "stopped"
            | "all";
        createdBy: number | null;
    }>;
    export type ExperimentResultsWidgetConfig = Partial<{
        experimentId: number | null;
    }>;
    export type SurveyResultsWidgetConfig = Partial<{
        dateRange: WidgetDateRange | null;
        surveyId: string | null;
        limit: number;
    }>;
    export type LogsListWidgetConfig = Partial<{
        dateRange: WidgetDateRange | null;
        limit: number;
        orderBy: "latest" | "earliest";
        severityLevels: Array<
            "trace" | "debug" | "info" | "warn" | "error" | "fatal"
        >;
        serviceNames: Array<string>;
        wrapLines: boolean;
        timezone: "UTC" | "local";
        savedViewId: string | null;
    }>;
    export type ConversationsRecentTicketsWidgetConfig = Partial<{
        limit: number;
        status: "new" | "open" | "pending" | "on_hold" | "resolved" | "all";
        priorities: Array<"low" | "medium" | "high" | "critical">;
        channel: "widget" | "email" | "slack" | "teams" | "github" | "all";
        assignees: Array<("me" | "unassigned") | WidgetAssigneeFilter>;
        search: string;
        savedViewId: string | null;
    }>;
    export type DashboardWidgetConfig =
        | ActivityEventsListWidgetConfig
        | ErrorTrackingListWidgetConfig
        | SessionReplayListWidgetConfig
        | ExperimentsListWidgetConfig
        | ExperimentResultsWidgetConfig
        | SurveyResultsWidgetConfig
        | LogsListWidgetConfig
        | ConversationsRecentTicketsWidgetConfig;
    export type DashboardPatchWidgetOpenApi = Partial<{
        id: string;
        widget_type: DashboardPatchWidgetOpenApiWidgetTypeEnum;
        config: DashboardWidgetConfig;
        name: string | null;
        description: string;
    }>;
    export type DashboardPatchTileOpenApi = Partial<{
        id: number;
        widget: DashboardPatchWidgetOpenApi;
    }>;
    export type DashboardTileBasic = {
        id: number;
        dashboard_id: number;
        deleted?: (boolean | null) | undefined;
    };
    export type DataTableNodeViewPropsContextType =
        | "event_definition"
        | "team_columns";
    export type DataTableNodeViewPropsContext = {
        eventDefinitionId?: (string | null) | undefined;
        type: DataTableNodeViewPropsContextType;
    };
    export type Response = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        nextCursor?: (string | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response1 = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        limit: number;
        missing_actors_count?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<string> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response2 = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        kind?: string | undefined;
        limit: number;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response3 = {
        clickhouse?: (string | null) | undefined;
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        explain?: (Array<string> | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        metadata?: (HogQLMetadataResponse | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query?: (string | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response4 = {
        dateFrom?: (string | null) | undefined;
        dateTo?: (string | null) | undefined;
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<WebOverviewItem>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response5 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStale?: (boolean | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response6 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response7 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response8 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebVitalsPathBreakdownResultItem = {
        path: string;
        value: number;
    };
    export type WebVitalsPathBreakdownResult = {
        good: Array<WebVitalsPathBreakdownResultItem>;
        needs_improvements: Array<WebVitalsPathBreakdownResultItem>;
        poor: Array<WebVitalsPathBreakdownResultItem>;
    };
    export type Response9 = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<WebVitalsPathBreakdownResult>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response10 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: unknown;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response11 = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type MarketingAnalyticsItem = {
        changeFromPreviousPct?: (number | null) | undefined;
        hasComparison?: (boolean | null) | undefined;
        isIncreaseBad?: (boolean | null) | undefined;
        key: string;
        kind: WebAnalyticsItemKind;
        previous?: (number | string | null) | undefined;
        value?: (number | string | null) | undefined;
    };
    export type Response12 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<MarketingAnalyticsItem>>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response13 = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Record<string, MarketingAnalyticsItem>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response14 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<MarketingAnalyticsItem>>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type VolumeBucket = { label: string; value: number };
    export type ErrorTrackingIssueAggregations = {
        occurrences: number;
        sessions: number;
        users: number;
        volumeRange?: (Array<number> | null) | undefined;
        volume_buckets: Array<VolumeBucket>;
    };
    export type ErrorTrackingIssueAssigneeType = "user" | "role";
    export type ErrorTrackingIssueAssignee = {
        id: string | number;
        type: ErrorTrackingIssueAssigneeType;
    };
    export type ErrorTrackingIssueCohort = { id: number; name: string };
    export type IntegrationKind =
        | "slack"
        | "salesforce"
        | "hubspot"
        | "google-pubsub"
        | "google-cloud-service-account"
        | "google-cloud-storage"
        | "google-ads"
        | "google-analytics"
        | "google-calendar"
        | "google-search-console"
        | "google-sheets"
        | "linkedin-ads"
        | "snapchat"
        | "stripe"
        | "intercom"
        | "email"
        | "twilio"
        | "linear"
        | "github"
        | "gitlab"
        | "meta-ads"
        | "instagram"
        | "clickup"
        | "reddit-ads"
        | "databricks"
        | "tiktok-ads"
        | "bing-ads"
        | "vercel"
        | "azure-blob"
        | "firebase"
        | "jira"
        | "pinterest-ads"
        | "pardot"
        | "customerio-app"
        | "customerio-webhook"
        | "customerio-track"
        | "apns"
        | "postgresql"
        | "aws-s3"
        | "aws-redshift"
        | "s3-compatible"
        | "snowflake"
        | "youtube-analytics";
    export type ErrorTrackingExternalReferenceIntegration = {
        display_name: string;
        id: number;
        kind: IntegrationKind;
    };
    export type ErrorTrackingExternalReference = {
        external_url: string;
        id: string;
        integration: ErrorTrackingExternalReferenceIntegration;
    };
    export type FirstEvent = {
        distinct_id: string;
        properties: string;
        timestamp: string;
        uuid: string;
    };
    export type LastEvent = {
        distinct_id: string;
        properties: string;
        timestamp: string;
        uuid: string;
    };
    export type ErrorTrackingQueryIssueSeverity =
        | "low"
        | "medium"
        | "high"
        | "critical";
    export type ErrorTrackingIssueStatus =
        | "archived"
        | "active"
        | "resolved"
        | "pending_release"
        | "suppressed";
    export type ErrorTrackingIssue = {
        aggregations?: (ErrorTrackingIssueAggregations | null) | undefined;
        assignee?: (ErrorTrackingIssueAssignee | null) | undefined;
        cohort?: (ErrorTrackingIssueCohort | null) | undefined;
        description?: (string | null) | undefined;
        external_issues?:
            | (Array<ErrorTrackingExternalReference> | null)
            | undefined;
        first_event?: (FirstEvent | null) | undefined;
        first_seen: string;
        function?: (string | null) | undefined;
        id: string;
        last_event?: (LastEvent | null) | undefined;
        last_seen: string;
        library?: (string | null) | undefined;
        name?: (string | null) | undefined;
        severity?: (ErrorTrackingQueryIssueSeverity | null) | undefined;
        source?: (string | null) | undefined;
        status: ErrorTrackingIssueStatus;
    };
    export type Response15 = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<ErrorTrackingIssue>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Population = {
        both: number;
        exception_only: number;
        neither: number;
        success_only: number;
    };
    export type ErrorTrackingCorrelatedIssue = {
        assignee?: (ErrorTrackingIssueAssignee | null) | undefined;
        cohort?: (ErrorTrackingIssueCohort | null) | undefined;
        description?: (string | null) | undefined;
        event: string;
        external_issues?:
            | (Array<ErrorTrackingExternalReference> | null)
            | undefined;
        first_seen: string;
        id: string;
        last_seen: string;
        library?: (string | null) | undefined;
        name?: (string | null) | undefined;
        odds_ratio: number;
        population: Population;
        severity?: (ErrorTrackingQueryIssueSeverity | null) | undefined;
        status: ErrorTrackingIssueStatus;
    };
    export type Response16 = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<ErrorTrackingCorrelatedIssue>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response17 = {
        credible_intervals: Record<string, Array<number>>;
        expected_loss: number;
        funnels_query?: (FunnelsQuery | null) | undefined;
        insight: Array<Array<Record<string, unknown>>>;
        kind?: string | undefined;
        probability: Record<string, number>;
        significance_code: ExperimentSignificanceCode;
        significant: boolean;
        stats_version?: (number | null) | undefined;
        variants: Array<ExperimentVariantFunnelsBaseStats>;
        warnings?: (Array<DataWarehouseSyncWarning> | null) | undefined;
    };
    export type Response18 = {
        count_query?: (TrendsQuery | null) | undefined;
        credible_intervals: Record<string, Array<number>>;
        exposure_query?: (TrendsQuery | null) | undefined;
        insight: Array<Record<string, unknown>>;
        kind?: string | undefined;
        p_value: number;
        probability: Record<string, number>;
        significance_code: ExperimentSignificanceCode;
        significant: boolean;
        stats_version?: (number | null) | undefined;
        variants: Array<ExperimentVariantTrendsBaseStats>;
        warnings?: (Array<DataWarehouseSyncWarning> | null) | undefined;
    };
    export type LLMSentimentMessage = {
        label: string;
        score: number;
        scores?: (Record<string, number> | null) | undefined;
    };
    export type LLMSentimentResult = {
        label: string;
        message_count?: (number | null) | undefined;
        messages?: (Record<string, LLMSentimentMessage> | null) | undefined;
        score: number;
        scores?: (Record<string, number> | null) | undefined;
    };
    export type LLMTraceEvent = {
        createdAt: string;
        event: AIEventType | string;
        id: string;
        properties: Record<string, unknown>;
        sentiment?: (LLMSentimentResult | null) | undefined;
    };
    export type LLMTracePerson = {
        created_at: string;
        distinct_id: string;
        properties: Record<string, unknown>;
        uuid: string;
    };
    export type LLMTrace = {
        aiSessionId?: (string | null) | undefined;
        createdAt: string;
        distinctId: string;
        errorCount?: (number | null) | undefined;
        events: Array<LLMTraceEvent>;
        id: string;
        inputCost?: (number | null) | undefined;
        inputState?: unknown | undefined;
        inputTokens?: (number | null) | undefined;
        isSupportTrace?: (boolean | null) | undefined;
        outputCost?: (number | null) | undefined;
        outputState?: unknown | undefined;
        outputTokens?: (number | null) | undefined;
        person?: (LLMTracePerson | null) | undefined;
        requestCost?: (number | null) | undefined;
        sentiment?: (LLMSentimentResult | null) | undefined;
        tools?: (Array<string> | null) | undefined;
        totalCost?: (number | null) | undefined;
        totalLatency?: (number | null) | undefined;
        traceName?: (string | null) | undefined;
        webSearchCost?: (number | null) | undefined;
    };
    export type Response19 = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<LLMTrace>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response21 = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response22 = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        kind?: string | undefined;
        limit: number;
        metricsResults?: (Array<number | null> | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type Response23 = {
        error?: (string | null) | undefined;
        hasMore: boolean;
        hogql?: (string | null) | undefined;
        kind?: string | undefined;
        limit: number;
        metricsResults?: (Array<number | null> | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<AccountsTableRow>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type TaxonomicFilterGroupType =
        | "metadata"
        | "actions"
        | "cohorts"
        | "cohorts_with_all"
        | "data_warehouse"
        | "data_warehouse_source_tables"
        | "data_warehouse_materialized_views"
        | "data_warehouse_properties"
        | "data_warehouse_person_properties"
        | "elements"
        | "events"
        | "internal_events"
        | "internal_event_properties"
        | "event_properties"
        | "event_feature_flags"
        | "event_metadata"
        | "numerical_event_properties"
        | "person_properties"
        | "person_metadata"
        | "pageview_urls"
        | "pageview_events"
        | "screens"
        | "screen_events"
        | "email_addresses"
        | "autocapture_events"
        | "custom_events"
        | "wildcard"
        | "groups"
        | "persons"
        | "feature_flags"
        | "insights"
        | "experiments"
        | "plugins"
        | "dashboards"
        | "name_groups"
        | "session_properties"
        | "hogql_expression"
        | "notebooks"
        | "log_entries"
        | "error_tracking_issues"
        | "logs"
        | "log_attributes"
        | "log_resource_attributes"
        | "metric_attributes"
        | "spans"
        | "span_attributes"
        | "span_resource_attributes"
        | "replay"
        | "replay_saved_filters"
        | "revenue_analytics_properties"
        | "account_fields"
        | "account_relationships"
        | "account_custom_properties"
        | "resources"
        | "error_tracking_properties"
        | "activity_log_properties"
        | "mcp_properties"
        | "max_ai_context"
        | "workflow_variables"
        | "suggested_filters"
        | "recent_filters"
        | "pinned_filters"
        | "empty";
    export type HrefMatching = "contains" | "exact" | "regex" | null;
    export type TextMatching = "contains" | "exact" | "regex" | null;
    export type UrlMatching = "contains" | "exact" | "regex" | null;
    export type EventsQueryActionStep = Partial<{
        event: string | null;
        href: string | null;
        href_matching: HrefMatching | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        selector: string | null;
        tag_name: string | null;
        text: string | null;
        text_matching: TextMatching | null;
        url: string | null;
        url_matching: UrlMatching | null;
    }>;
    export type EventsQueryResponse = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        nextCursor?: (string | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type EventsQuery = {
        actionId?: (number | null) | undefined;
        actionSteps?: (Array<EventsQueryActionStep> | null) | undefined;
        after?: (string | null) | undefined;
        before?: (string | null) | undefined;
        event?: (string | null) | undefined;
        events?: (Array<string> | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        fixedProperties?:
            | (Array<
                  | PropertyGroupFilter
                  | PropertyGroupFilterValue
                  | (
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    )
              > | null)
            | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?: (Array<string> | null) | undefined;
        personId?: (string | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (EventsQueryResponse | null) | undefined;
        /**
         * Return a limited set of data. Required.
         */
        select: Array<string>;
        source?: (InsightActorsQuery | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
        where?: (Array<string> | null) | undefined;
    };
    export type PersonsNode = Partial<{
        cohort: number | null;
        distinctId: string | null;
        fixedProperties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        kind: string;
        limit: number | null;
        modifiers: HogQLQueryModifiers | null;
        offset: number | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        response: Record<string, unknown> | null;
        search: string | null;
        tags: QueryLogTags | null;
        version: number | null;
    }>;
    export type GroupsQueryResponse = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        kind?: string | undefined;
        limit: number;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset: number;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type GroupsQuery = {
        group_type_index: number;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?: (Array<string> | null) | undefined;
        properties?:
            | (Array<GroupPropertyFilter | HogQLPropertyFilter> | null)
            | undefined;
        response?: (GroupsQueryResponse | null) | undefined;
        search?: (string | null) | undefined;
        select?: (Array<string> | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebExternalClicksTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebExternalClicksTableQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebExternalClicksTableQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        stripQueryParams?: (boolean | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebBotsBreakdown = "Crawler" | "Path";
    export type WebBotsTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebBotsTableQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        breakdownBy: WebBotsBreakdown;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebBotsTableQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebGoalsQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebGoalsQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebGoalsQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        useWebAnalyticsPrecompute?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebVitalsQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebGoalsQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        source:
            | TrendsQuery
            | FunnelsQuery
            | RetentionQuery
            | PathsQuery
            | PathsV2Query
            | StickinessQuery
            | LifecycleQuery
            | WebStatsTableQuery
            | WebOverviewQuery;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type WebVitalsMetric = "INP" | "LCP" | "CLS" | "FCP";
    export type WebVitalsPercentile = "p75" | "p90" | "p99";
    export type WebVitalsPathBreakdownQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        preComputeIneligibleReason?: (string | null) | undefined;
        preComputeStrategy?:
            | (WebAnalyticsPreComputeStrategy | null)
            | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<WebVitalsPathBreakdownResult>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type WebVitalsPathBreakdownQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        metric: WebVitalsMetric;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        orderBy?:
            | (Array<
                  WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection
              > | null)
            | undefined;
        percentile: WebVitalsPercentile;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (WebVitalsPathBreakdownQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        thresholds: Array<number>;
        useSessionsTable?: (boolean | null) | undefined;
        useWebAnalyticsPrecompute?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type Filters = Partial<{
        dateRange: DateRange | null;
        properties: Array<SessionPropertyFilter> | null;
    }>;
    export type SessionAttributionGroupBy =
        | "ChannelType"
        | "Medium"
        | "Source"
        | "Campaign"
        | "AdIds"
        | "ReferringDomain"
        | "InitialURL";
    export type SessionAttributionExplorerQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: unknown;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type SessionAttributionExplorerQuery = {
        filters?: (Filters | null) | undefined;
        groupBy: Array<SessionAttributionGroupBy>;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        response?: (SessionAttributionExplorerQueryResponse | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type SessionsQueryResponse = {
        columns: Array<unknown>;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        /**
         * Generated HogQL query.
         */
        hogql: string;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<unknown>>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types: Array<string>;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type SessionsQuery = {
        actionId?: (number | null) | undefined;
        after?: (string | null) | undefined;
        before?: (string | null) | undefined;
        event?: (string | null) | undefined;
        eventProperties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        fixedProperties?:
            | (Array<
                  | PropertyGroupFilter
                  | PropertyGroupFilterValue
                  | (
                        | EventPropertyFilter
                        | PersonPropertyFilter
                        | PersonMetadataPropertyFilter
                        | ElementPropertyFilter
                        | EventMetadataPropertyFilter
                        | SessionPropertyFilter
                        | CohortPropertyFilter
                        | RecordingPropertyFilter
                        | LogEntryPropertyFilter
                        | GroupPropertyFilter
                        | FeaturePropertyFilter
                        | FlagPropertyFilter
                        | HogQLPropertyFilter
                        | EmptyPropertyFilter
                        | DataWarehousePropertyFilter
                        | DataWarehousePersonPropertyFilter
                        | ErrorTrackingIssueFilter
                        | LogPropertyFilter
                        | MetricPropertyFilter
                        | SpanPropertyFilter
                        | RevenueAnalyticsPropertyFilter
                        | AccountCustomPropertyFilter
                        | WorkflowVariablePropertyFilter
                        | BehavioralPropertyFilter
                    )
              > | null)
            | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?: (Array<string> | null) | undefined;
        personId?: (string | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (SessionsQueryResponse | null) | undefined;
        /**
         * Return a limited set of data. Required.
         */
        select: Array<string>;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
        where?: (Array<string> | null) | undefined;
    };
    export type MarketingAnalyticsDrillDownLevel =
        | "channel"
        | "channel_source"
        | "source"
        | "campaign"
        | "ad_group"
        | "ad"
        | "medium"
        | "content"
        | "term";
    export type IntegrationFilter = Partial<{
        integrationSourceIds: Array<string> | null;
    }>;
    export type MarketingAnalyticsOrderByEnum = "ASC" | "DESC";
    export type MarketingAnalyticsTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<MarketingAnalyticsItem>>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type MarketingAnalyticsTableQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        draftConversionGoal?:
            | (
                  | ConversionGoalFilter1
                  | ConversionGoalFilter2
                  | ConversionGoalFilter3
                  | null
              )
            | undefined;
        drillDownLevel?: (MarketingAnalyticsDrillDownLevel | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        integrationFilter?: (IntegrationFilter | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?:
            | (Array<Array<string | MarketingAnalyticsOrderByEnum>> | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?: (MarketingAnalyticsTableQueryResponse | null) | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        select?: (Array<string> | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type MarketingAnalyticsAggregatedQueryResponse = {
        error?: (string | null) | undefined;
        hogql?: (string | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Record<string, MarketingAnalyticsItem>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type MarketingAnalyticsAggregatedQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        draftConversionGoal?:
            | (
                  | ConversionGoalFilter1
                  | ConversionGoalFilter2
                  | ConversionGoalFilter3
                  | null
              )
            | undefined;
        drillDownLevel?: (MarketingAnalyticsDrillDownLevel | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        integrationFilter?: (IntegrationFilter | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?:
            | (MarketingAnalyticsAggregatedQueryResponse | null)
            | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        select?: (Array<string> | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type NonIntegratedConversionsTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<Array<MarketingAnalyticsItem>>;
        samplingRate?: (SamplingRate | null) | undefined;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type NonIntegratedConversionsTableQuery = {
        aggregation_group_type_index?: (number | null) | undefined;
        compareFilter?: (CompareFilter | null) | undefined;
        conversionGoal?:
            | (ActionConversionGoal | CustomEventConversionGoal | null)
            | undefined;
        dataColorTheme?: (number | null) | undefined;
        dateRange?: (DateRange | null) | undefined;
        doPathCleaning?: (boolean | null) | undefined;
        draftConversionGoal?:
            | (
                  | ConversionGoalFilter1
                  | ConversionGoalFilter2
                  | ConversionGoalFilter3
                  | null
              )
            | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        includeRevenue?: (boolean | null) | undefined;
        interval?: (IntervalType | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?:
            | (Array<Array<string | MarketingAnalyticsOrderByEnum>> | null)
            | undefined;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
        >;
        response?:
            | (NonIntegratedConversionsTableQueryResponse | null)
            | undefined;
        sampling?: (WebAnalyticsSampling | null) | undefined;
        samplingFactor?: (number | null) | undefined;
        select?: (Array<string> | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useSessionsTable?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ErrorTrackingOrderBy =
        | "last_seen"
        | "first_seen"
        | "occurrences"
        | "users"
        | "sessions";
    export type OrderDirection2 = "ASC" | "DESC";
    export type ErrorTrackingPendingFingerprintIssueStateUpdate = {
        assigned_role_id?: (string | null) | undefined;
        assigned_user_id?: (number | null) | undefined;
        fingerprint: string;
        /**
         * ISO 8601 datetime string.
         */
        first_seen: string;
        is_deleted: number;
        issue_description?: (string | null) | undefined;
        issue_id: string;
        issue_name?: (string | null) | undefined;
        issue_severity?: (ErrorTrackingQueryIssueSeverity | null) | undefined;
        issue_status: string;
        /**
         * Client-stamped monotonic version (`Date.now()` ms at mutation success).
         */
        version: number;
    };
    export type ErrorTrackingQueryResponse = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<ErrorTrackingIssue>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type ErrorTrackingQuery = {
        assignee?: (ErrorTrackingIssueAssignee | null) | undefined;
        /**
         * Date range to filter results.
         */
        dateRange: DateRange;
        filterGroup?: (PropertyGroupFilter | null) | undefined;
        filterTestAccounts?: (boolean | null) | undefined;
        groupKey?: (string | null) | undefined;
        groupTypeIndex?: (number | null) | undefined;
        issueId?: (string | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        /**
         * Field to sort results by.
         */
        orderBy: ErrorTrackingOrderBy;
        orderDirection?: (OrderDirection2 | null) | undefined;
        pendingFingerprintIssueStateUpdates?:
            | (Array<ErrorTrackingPendingFingerprintIssueStateUpdate> | null)
            | undefined;
        personId?: (string | null) | undefined;
        response?: (ErrorTrackingQueryResponse | null) | undefined;
        searchQuery?: (string | null) | undefined;
        status?: (ErrorTrackingIssueStatus | string | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        useQueryV2?: (boolean | null) | undefined;
        useQueryV3?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
        volumeResolution: number;
        withAggregations?: (boolean | null) | undefined;
        withFirstEvent?: (boolean | null) | undefined;
        withLastEvent?: (boolean | null) | undefined;
    };
    export type ErrorTrackingIssueCorrelationQueryResponse = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<ErrorTrackingCorrelatedIssue>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type ErrorTrackingIssueCorrelationQuery = {
        events: Array<string>;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        response?:
            | (ErrorTrackingIssueCorrelationQueryResponse | null)
            | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ExperimentFunnelsQueryResponse = {
        credible_intervals: Record<string, Array<number>>;
        expected_loss: number;
        funnels_query?: (FunnelsQuery | null) | undefined;
        insight: Array<Array<Record<string, unknown>>>;
        kind?: string | undefined;
        probability: Record<string, number>;
        significance_code: ExperimentSignificanceCode;
        significant: boolean;
        stats_version?: (number | null) | undefined;
        variants: Array<ExperimentVariantFunnelsBaseStats>;
        warnings?: (Array<DataWarehouseSyncWarning> | null) | undefined;
    };
    export type ExperimentFunnelsQuery = {
        experiment_id?: (number | null) | undefined;
        fingerprint?: (string | null) | undefined;
        funnels_query: FunnelsQuery;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        name?: (string | null) | undefined;
        response?: (ExperimentFunnelsQueryResponse | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        uuid?: (string | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type ExperimentTrendsQueryResponse = {
        count_query?: (TrendsQuery | null) | undefined;
        credible_intervals: Record<string, Array<number>>;
        exposure_query?: (TrendsQuery | null) | undefined;
        insight: Array<Record<string, unknown>>;
        kind?: string | undefined;
        p_value: number;
        probability: Record<string, number>;
        significance_code: ExperimentSignificanceCode;
        significant: boolean;
        stats_version?: (number | null) | undefined;
        variants: Array<ExperimentVariantTrendsBaseStats>;
        warnings?: (Array<DataWarehouseSyncWarning> | null) | undefined;
    };
    export type ExperimentTrendsQuery = {
        count_query: TrendsQuery;
        experiment_id?: (number | null) | undefined;
        exposure_query?: (TrendsQuery | null) | undefined;
        fingerprint?: (string | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        name?: (string | null) | undefined;
        response?: (ExperimentTrendsQueryResponse | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        uuid?: (string | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type TracesQueryResponse = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<LLMTrace>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type TracesQuery = Partial<{
        dateRange: DateRange | null;
        filterSupportTraces: boolean | null;
        filterTestAccounts: boolean | null;
        groupKey: string | null;
        groupTypeIndex: number | null;
        includeSentiment: boolean | null;
        kind: string;
        limit: number | null;
        modifiers: HogQLQueryModifiers | null;
        offset: number | null;
        personId: string | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
        randomOrder: boolean | null;
        response: TracesQueryResponse | null;
        searchTerm: string | null;
        showColumnConfigurator: boolean | null;
        tags: QueryLogTags | null;
        version: number | null;
    }>;
    export type TraceQueryResponse = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<LLMTrace>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type TraceQuery = {
        dateRange?: (DateRange | null) | undefined;
        includeSentiment?: (boolean | null) | undefined;
        kind?: string | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | PersonMetadataPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | MetricPropertyFilter
                  | SpanPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                  | AccountCustomPropertyFilter
                  | WorkflowVariablePropertyFilter
                  | BehavioralPropertyFilter
              > | null)
            | undefined;
        response?: (TraceQueryResponse | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        traceId: string;
        version?: (number | null) | undefined;
    };
    export type SessionQueryResponse = {
        columns?: (Array<string> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<LLMTrace>;
        timings?: (Array<QueryTiming> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type SessionQuery = {
        dateRange?: (DateRange | null) | undefined;
        includeSentiment?: (boolean | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        response?: (SessionQueryResponse | null) | undefined;
        sessionId: string;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type EndpointsUsageBreakdown =
        | "Endpoint"
        | "MaterializationType"
        | "ApiKey"
        | "Status";
    export type MaterializationType = "materialized" | "inline" | null;
    export type EndpointsUsageOrderByField =
        | "requests"
        | "bytes_read"
        | "cpu_seconds"
        | "avg_query_duration_ms"
        | "error_rate";
    export type EndpointsUsageOrderByDirection = "ASC" | "DESC";
    export type EndpointsUsageTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined;
        error?: (string | null) | undefined;
        hasMore?: (boolean | null) | undefined;
        hogql?: (string | null) | undefined;
        limit?: (number | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        query_status?: (QueryStatus | null) | undefined;
        resolved_compare_date_range?:
            | (ResolvedDateRangeResponse | null)
            | undefined;
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined;
        results: Array<unknown>;
        timings?: (Array<QueryTiming> | null) | undefined;
        types?: (Array<unknown> | null) | undefined;
        used_data_warehouse_sources?:
            | (Array<DataWarehouseSourceUsage> | null)
            | undefined;
        warnings?:
            | (Array<
                  DataWarehouseSyncWarning | AccessControlFilterWarning
              > | null)
            | undefined;
    };
    export type EndpointsUsageTableQuery = {
        breakdownBy: EndpointsUsageBreakdown;
        dateRange?: (DateRange | null) | undefined;
        endpointNames?: (Array<string> | null) | undefined;
        kind?: string | undefined;
        limit?: (number | null) | undefined;
        materializationType?: (MaterializationType | null) | undefined;
        modifiers?: (HogQLQueryModifiers | null) | undefined;
        offset?: (number | null) | undefined;
        orderBy?:
            | (Array<
                  EndpointsUsageOrderByField | EndpointsUsageOrderByDirection
              > | null)
            | undefined;
        response?: (EndpointsUsageTableQueryResponse | null) | undefined;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type DataTableNode = {
        allowSorting?: (boolean | null) | undefined;
        columns?: (Array<string> | null) | undefined;
        context?: (DataTableNodeViewPropsContext | null) | undefined;
        contextKey?: (string | null) | undefined;
        defaultColumns?: (Array<string> | null) | undefined;
        embedded?: (boolean | null) | undefined;
        expandable?: (boolean | null) | undefined;
        full?: (boolean | null) | undefined;
        hiddenColumns?: (Array<string> | null) | undefined;
        kind?: string | undefined;
        pinnedColumns?: (Array<string> | null) | undefined;
        propertiesViaUrl?: (boolean | null) | undefined;
        response?:
            | (
                  | Record<string, unknown>
                  | Response
                  | Response1
                  | Response2
                  | Response3
                  | Response4
                  | Response5
                  | Response6
                  | Response7
                  | Response8
                  | Response9
                  | Response10
                  | Response11
                  | Response12
                  | Response13
                  | Response14
                  | Response15
                  | Response16
                  | Response17
                  | Response18
                  | Response19
                  | Response21
                  | Response22
                  | Response23
                  | null
              )
            | undefined;
        showAbsoluteTime?: (boolean | null) | undefined;
        showActions?: (boolean | null) | undefined;
        showColumnConfigurator?: (boolean | null) | undefined;
        showCount?: (boolean | null) | undefined;
        showDateRange?: (boolean | null) | undefined;
        showElapsedTime?: (boolean | null) | undefined;
        showEventFilter?: (boolean | null) | undefined;
        showEventsFilter?: (boolean | null) | undefined;
        showExport?: (boolean | null) | undefined;
        showHogQLEditor?: (boolean | null) | undefined;
        showOpenEditorButton?: (boolean | null) | undefined;
        showPersistentColumnConfigurator?: (boolean | null) | undefined;
        showPropertyFilter?:
            | (boolean | Array<TaxonomicFilterGroupType> | null)
            | undefined;
        showRecordingColumn?: (boolean | null) | undefined;
        showReload?: (boolean | null) | undefined;
        showResultsTable?: (boolean | null) | undefined;
        showSavedFilters?: (boolean | null) | undefined;
        showSavedQueries?: (boolean | null) | undefined;
        showSearch?: (boolean | null) | undefined;
        showSourceQueryOptions?: (boolean | null) | undefined;
        showTableViews?: (boolean | null) | undefined;
        showTestAccountFilters?: (boolean | null) | undefined;
        showTimings?: (boolean | null) | undefined;
        /**
         * Source of the events
         */
        source:
            | EventsNode
            | EventsQuery
            | PersonsNode
            | ActorsQuery
            | GroupsQuery
            | HogQLQuery
            | WebOverviewQuery
            | WebStatsTableQuery
            | WebExternalClicksTableQuery
            | WebBotsTableQuery
            | WebGoalsQuery
            | WebVitalsQuery
            | WebVitalsPathBreakdownQuery
            | SessionAttributionExplorerQuery
            | SessionsQuery
            | MarketingAnalyticsTableQuery
            | MarketingAnalyticsAggregatedQuery
            | NonIntegratedConversionsTableQuery
            | ErrorTrackingQuery
            | ErrorTrackingIssueCorrelationQuery
            | ExperimentFunnelsQuery
            | ExperimentTrendsQuery
            | TracesQuery
            | TraceQuery
            | SessionQuery
            | EndpointsUsageTableQuery
            | AccountsQuery
            | AccountsTableQuery;
        tags?: (QueryLogTags | null) | undefined;
        version?: (number | null) | undefined;
    };
    export type TableSettings = Partial<{
        columns: Array<ChartAxis> | null;
        conditionalFormatting: Array<ConditionalFormattingRule> | null;
        pinnedColumns: Array<string> | null;
        transpose: boolean | null;
    }>;
    export type DataVisualizationNode = {
        chartSettings?: (ChartSettings | null) | undefined;
        display?: (ChartDisplayType | null) | undefined;
        kind?: string | undefined;
        source: HogQLQuery;
        tableSettings?: (TableSettings | null) | undefined;
        version?: (number | null) | undefined;
    };
    /**
     * * `html` - html
     * * `text` - text
     */
    export type DescriptionContentTypeEnum = "html" | "text";
    /**
     * * `startup_plan` - startup_plan
     * * `prepaid_credits` - prepaid_credits
     */
    export type DesktopAccessReasonEnum = "startup_plan" | "prepaid_credits";
    /**
     * * `Desktop` - Desktop
     * * `Mobile` - Mobile
     * * `Tablet` - Tablet
     */
    export type DeviceTypesEnum = "Desktop" | "Mobile" | "Tablet";
    /**
     * * `off` - Off
     * * `opt_out` - Opt Out
     * * `opt_in` - Opt In
     */
    export type EmailTrackingConsentModeEnum = "off" | "opt_out" | "opt_in";
    /**
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake
     * * `redshift` - redshift
     * * `clickhouse` - clickhouse
     * * `motherduck` - motherduck
     * * `trino` - trino
     */
    export type EngineEnum =
        | "duckdb"
        | "postgres"
        | "mysql"
        | "snowflake"
        | "redshift"
        | "clickhouse"
        | "motherduck"
        | "trino";
    export type ErrorTrackingExternalReferenceIntegrationResult = {
        /**
         * ID of the integration backing this external reference.
         */
        id: number;
        /**
         * Integration provider, e.g. 'github', 'gitlab', 'linear', or 'jira'.
         */
        kind: string;
        /**
         * Human-readable name of the connected integration.
         */
        display_name: string;
    };
    /**
     * Read-only shape of an external reference, shared by every response.
     */
    export type ErrorTrackingExternalReferenceResult = {
        /**
         * Unique ID of the external reference.
         */
        id: string;
        /**
         * The connected integration this reference was created through.
         */
        integration: ErrorTrackingExternalReferenceIntegrationResult & unknown;
        /**
         * URL of the linked external issue in the provider's system.
         */
        external_url: string;
    };
    export type ErrorTrackingIssueAssigneeRead = {
        id: number | string | null;
        type: string;
    };
    export type ErrorTrackingIssueCohortRead = { id: number; name: string };
    export type ErrorTrackingIssueSeverity =
        | "low"
        | "medium"
        | "high"
        | "critical";
    /**
     * Read-only serializer for issue contract types returned by the facade.
     */
    export type ErrorTrackingIssueRead = {
        id: string;
        status: string;
        /**
         * Issue severity, or null when no severity is assigned.
         */
        severity: ErrorTrackingIssueSeverity | null;
        name: string | null;
        description: string | null;
        first_seen: string | null;
        assignee: ErrorTrackingIssueAssigneeRead | null;
        external_issues: Array<ErrorTrackingExternalReferenceResult>;
        cohort: ErrorTrackingIssueCohortRead | null;
    };
    /**
     * * `active` - active
     * * `resolved` - resolved
     * * `suppressed` - suppressed
     */
    export type ErrorTrackingIssueWriteStatusEnum =
        | "active"
        | "resolved"
        | "suppressed";
    export type ErrorTrackingIssueWrite = Partial<{
        status: ErrorTrackingIssueWriteStatusEnum;
        severity: ErrorTrackingIssueSeverity | null;
        name: string | null;
        description: string | null;
    }>;
    /**
     * * `active` - Active
     * * `paused` - Paused
     * * `error` - Error
     */
    export type EvaluationStatusEnum = "active" | "paused" | "error";
    /**
     * * `provider_key_required` - No provider API key configured
     * * `provider_key_deleted` - Provider API key was deleted
     * * `no_default_model` - No default model available for the selected provider
     * * `provider_key_invalid` - Provider API key is invalid
     * * `provider_key_permission_denied` - Provider API key lacks model access
     * * `provider_key_quota_exceeded` - Provider API key quota exceeded
     * * `provider_key_rate_limited` - Provider API key is rate limited
     * * `model_not_found` - Model not found
     * * `hog_error` - Hog evaluation code failed
     */
    export type EvaluationStatusReasonEnum =
        | "provider_key_required"
        | "provider_key_deleted"
        | "no_default_model"
        | "provider_key_invalid"
        | "provider_key_permission_denied"
        | "provider_key_quota_exceeded"
        | "provider_key_rate_limited"
        | "model_not_found"
        | "hog_error";
    /**
     * * `llm_judge` - LLM as a judge
     * * `hog` - Hog
     * * `sentiment` - Sentiment analysis
     */
    export type EvaluationTypeEnum = "llm_judge" | "hog" | "sentiment";
    /**
     * * `boolean` - Boolean (Pass/Fail)
     * * `sentiment` - Sentiment
     */
    export type OutputTypeEnum = "boolean" | "sentiment";
    /**
     * A trigger condition set controlling which generations an evaluation runs on.
     */
    export type EvaluationCondition = {
        /**
         * Stable identifier for this condition set.
         */
        id: string;
        /**
         * A trigger condition set controlling which generations an evaluation runs on.
         */
        rollout_percentage?: number | undefined;
        /**
         * A trigger condition set controlling which generations an evaluation runs on.
         */
        properties?: Array<Record<string, unknown>> | undefined;
    };
    /**
     * * `generation` - Generation
     * * `trace` - Trace
     * * `session` - Session
     */
    export type EvaluationTargetEnum = "generation" | "trace" | "session";
    /**
     * * `openai` - Openai
     * * `anthropic` - Anthropic
     * * `gemini` - Gemini
     * * `openrouter` - Openrouter
     * * `fireworks` - Fireworks
     * * `azure_openai` - Azure OpenAI
     * * `together_ai` - Together AI
     * * `minimax` - MiniMax
     * * `zeabur` - Zeabur AI Hub
     */
    export type LLMProviderEnum =
        | "openai"
        | "anthropic"
        | "gemini"
        | "openrouter"
        | "fireworks"
        | "azure_openai"
        | "together_ai"
        | "minimax"
        | "zeabur";
    /**
     * Nested serializer for model configuration.
     */
    export type ModelConfiguration = {
        provider: LLMProviderEnum;
        model: string;
        /**
         * Nested serializer for model configuration.
         */
        provider_key_id?: (string | null) | undefined;
        provider_key_name: string | null;
    };
    /**
     * An evaluation that scores LLM generations, traces, or sessions.
     */
    export type Evaluation = {
        id: string;
        /**
         * Name of the evaluation.
         */
        name: string;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        description?: string | undefined;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        directory_id?: (string | null) | undefined;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        enabled?: boolean | undefined;
        status: EvaluationStatusEnum & unknown;
        status_reason: EvaluationStatusReasonEnum | NullEnum;
        /**
         * Additional detail for the current system-disabled status. This is only populated when the detail is safe to show in the evaluation UI.
         */
        status_reason_detail: string | null;
        /**
         * 'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment (trained on English, so use 'llm_judge' for multilingual agents).
         *
         * * `llm_judge` - LLM as a judge
         * * `hog` - Hog
         * * `sentiment` - Sentiment analysis
         */
        evaluation_type: EvaluationTypeEnum;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        evaluation_config?:
            | (
                  | {
                        /**
                         * Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.
                         */
                        prompt: string;
                    }
                  | {
                        /**
                         * Hog source code. Must return true (pass), false (fail), or null for N/A.
                         */
                        source: string;
                    }
                  | Partial<{
                        /**
                         * Classify sentiment from user messages in the generation input. The classifier is trained on English, so labels are unreliable for other languages; use an 'llm_judge' evaluation for multilingual agents.
                         */
                        source: "user_messages";
                    }>
              )
            | undefined;
        /**
         * Output format. Use 'boolean' for pass/fail evaluations and 'sentiment' for sentiment analysis.
         *
         * * `boolean` - Boolean (Pass/Fail)
         * * `sentiment` - Sentiment
         */
        output_type: OutputTypeEnum;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        output_config?:
            | Partial<{
                  /**
                   * Whether the evaluation can return N/A for non-applicable generations.
                   */
                  allows_na: boolean;
              }>
            | undefined;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        conditions?: Array<EvaluationCondition> | undefined;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        target?: EvaluationTargetEnum | undefined;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        target_config?:
            | (
                  | {
                        /**
                         * Wait a fixed window after the first matching generation, then evaluate.
                         */
                        strategy: "fixed_window";
                        window_seconds?: number | undefined;
                    }
                  | {
                        /**
                         * Evaluate once the unit has had no new activity for the quiet period.
                         */
                        strategy: "inactivity";
                        quiet_period_seconds?: number | undefined;
                        max_age_seconds?: number | undefined;
                    }
              )
            | undefined;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        model_configuration?: (ModelConfiguration | null) | undefined;
        created_at: string;
        updated_at: string;
        /**
         * User who created the evaluation.
         */
        created_by: UserBasic | null;
        /**
         * An evaluation that scores LLM generations, traces, or sessions.
         */
        deleted?: boolean | undefined;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    /**
     * * `server` - Server
     * * `client` - Client
     * * `all` - All
     */
    export type EvaluationRuntimeEnum = "server" | "client" | "all";
    /**
     * * `allow` - Allow
     * * `reject` - Reject
     */
    export type SchemaEnforcementModeEnum = "allow" | "reject";
    /**
     * Serializer mixin that handles tags for objects.
     */
    export type EventDefinitionRecord = {
        id: string;
        name: string;
        /**
         * Serializer mixin that handles tags for objects.
         */
        created_at?: (string | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        last_seen_at?: (string | null) | undefined;
        last_updated_at: string;
        /**
         * Serializer mixin that handles tags for objects.
         */
        tags?: Array<unknown> | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        enforcement_mode?: SchemaEnforcementModeEnum | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        primary_property?: (string | null) | undefined;
        is_action: boolean;
        action_id: number;
        is_calculating: boolean;
        last_calculated_at: string;
        created_by: UserBasic & unknown;
        /**
         * Serializer mixin that handles tags for objects.
         */
        post_to_slack?: boolean | undefined;
    };
    /**
     * * `exit_on_conversion` - Conversion
     * * `exit_on_trigger_not_matched` - Trigger Not Matched
     * * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
     * * `exit_only_at_end` - Only At End
     */
    export type ExitConditionEnum =
        | "exit_on_conversion"
        | "exit_on_trigger_not_matched"
        | "exit_on_trigger_not_matched_or_conversion"
        | "exit_only_at_end";
    export type MinimalFeatureFlag = {
        id: number;
        team_id: number;
        name?: string | undefined;
        key: string;
        filters?: Record<string, unknown> | undefined;
        deleted?: boolean | undefined;
        active?: boolean | undefined;
        ensure_experience_continuity?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
        evaluation_runtime?:
            | (EvaluationRuntimeEnum | BlankEnum | NullEnum)
            | undefined;
        bucketing_identifier?:
            | (BucketingIdentifierEnum | BlankEnum | NullEnum)
            | undefined;
        evaluation_contexts: Array<string>;
    };
    /**
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group
     */
    export type PropertyGroupTypeEnum = "cohort" | "person" | "group";
    /**
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `starts_with` - starts_with
     * * `not_starts_with` - not_starts_with
     * * `ends_with` - ends_with
     * * `not_ends_with` - not_ends_with
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `gte` - gte
     * * `lt` - lt
     * * `lte` - lte
     */
    export type FeatureFlagFilterPropertyGenericSchemaOperatorEnum =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "starts_with"
        | "not_starts_with"
        | "ends_with"
        | "not_ends_with"
        | "regex"
        | "not_regex"
        | "gt"
        | "gte"
        | "lt"
        | "lte";
    export type FeatureFlagFilterPropertyGenericSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        type?: PropertyGroupTypeEnum | undefined;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Comparison value for the property filter. Supports strings, numbers, booleans, and arrays.
         */
        value: unknown;
        /**
         * Operator used to compare the property value.
         *
         * * `exact` - exact
         * * `is_not` - is_not
         * * `icontains` - icontains
         * * `not_icontains` - not_icontains
         * * `starts_with` - starts_with
         * * `not_starts_with` - not_starts_with
         * * `ends_with` - ends_with
         * * `not_ends_with` - not_ends_with
         * * `regex` - regex
         * * `not_regex` - not_regex
         * * `gt` - gt
         * * `gte` - gte
         * * `lt` - lt
         * * `lte` - lte
         */
        operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnum;
    };
    export type FeatureFlagFilterPropertyExistsSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        type?: PropertyGroupTypeEnum | undefined;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Existence operator.
         *
         * * `is_set` - is_set
         * * `is_not_set` - is_not_set
         */
        operator: ExistenceOperatorEnum;
        value?: unknown | undefined;
    };
    export type FeatureFlagFilterPropertyDateSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        type?: PropertyGroupTypeEnum | undefined;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Date comparison operator.
         *
         * * `is_date_exact` - is_date_exact
         * * `is_date_after` - is_date_after
         * * `is_date_before` - is_date_before
         */
        operator: DateOperatorEnum;
        /**
         * Date value in ISO format or relative date expression.
         */
        value: string;
    };
    /**
     * * `semver_gt` - semver_gt
     * * `semver_gte` - semver_gte
     * * `semver_lt` - semver_lt
     * * `semver_lte` - semver_lte
     * * `semver_eq` - semver_eq
     * * `semver_neq` - semver_neq
     * * `semver_tilde` - semver_tilde
     * * `semver_caret` - semver_caret
     * * `semver_wildcard` - semver_wildcard
     */
    export type FeatureFlagFilterPropertySemverSchemaOperatorEnum =
        | "semver_gt"
        | "semver_gte"
        | "semver_lt"
        | "semver_lte"
        | "semver_eq"
        | "semver_neq"
        | "semver_tilde"
        | "semver_caret"
        | "semver_wildcard";
    export type FeatureFlagFilterPropertySemverSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        type?: PropertyGroupTypeEnum | undefined;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Semantic version comparison operator.
         *
         * * `semver_gt` - semver_gt
         * * `semver_gte` - semver_gte
         * * `semver_lt` - semver_lt
         * * `semver_lte` - semver_lte
         * * `semver_eq` - semver_eq
         * * `semver_neq` - semver_neq
         * * `semver_tilde` - semver_tilde
         * * `semver_caret` - semver_caret
         * * `semver_wildcard` - semver_wildcard
         */
        operator: FeatureFlagFilterPropertySemverSchemaOperatorEnum;
        /**
         * Semantic version string.
         */
        value: string;
    };
    /**
     * * `icontains_multi` - icontains_multi
     * * `not_icontains_multi` - not_icontains_multi
     */
    export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnum =
        | "icontains_multi"
        | "not_icontains_multi";
    export type FeatureFlagFilterPropertyMultiContainsSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        type?: PropertyGroupTypeEnum | undefined;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Multi-contains operator.
         *
         * * `icontains_multi` - icontains_multi
         * * `not_icontains_multi` - not_icontains_multi
         */
        operator: FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnum;
        /**
         * List of strings to evaluate against.
         */
        value: Array<string>;
    };
    /**
     * * `cohort` - cohort
     */
    export type FeatureFlagFilterPropertyCohortInSchemaTypeEnum = "cohort";
    /**
     * * `in` - in
     * * `not_in` - not_in
     */
    export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnum =
        | "in"
        | "not_in";
    export type FeatureFlagFilterPropertyCohortInSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        /**
         * Cohort property type required for in/not_in operators.
         *
         * * `cohort` - cohort
         */
        type: FeatureFlagFilterPropertyCohortInSchemaTypeEnum;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Membership operator for cohort properties.
         *
         * * `in` - in
         * * `not_in` - not_in
         */
        operator: FeatureFlagFilterPropertyCohortInSchemaOperatorEnum;
        /**
         * Cohort comparison value (single or list, depending on usage).
         */
        value: unknown;
    };
    /**
     * * `flag` - flag
     */
    export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnum = "flag";
    /**
     * * `flag_evaluates_to` - flag_evaluates_to
     */
    export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnum =
        "flag_evaluates_to";
    export type FeatureFlagFilterPropertyFlagEvaluatesSchema = {
        /**
         * Property key used in this feature flag condition.
         */
        key: string;
        /**
         * Flag property type required for flag dependency checks.
         *
         * * `flag` - flag
         */
        type: FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnum;
        cohort_name?: (string | null) | undefined;
        group_type_index?: (number | null) | undefined;
        /**
         * Operator for feature flag dependency evaluation.
         *
         * * `flag_evaluates_to` - flag_evaluates_to
         */
        operator: FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnum;
        /**
         * Value to compare flag evaluation against.
         */
        value: unknown;
    };
    export type FeatureFlagFilterPropertySchema =
        | FeatureFlagFilterPropertyGenericSchema
        | FeatureFlagFilterPropertyExistsSchema
        | FeatureFlagFilterPropertyDateSchema
        | FeatureFlagFilterPropertySemverSchema
        | FeatureFlagFilterPropertyMultiContainsSchema
        | FeatureFlagFilterPropertyCohortInSchema
        | FeatureFlagFilterPropertyFlagEvaluatesSchema;
    export type FeatureFlagConditionGroupSchema = Partial<{
        properties: Array<FeatureFlagFilterPropertySchema>;
        rollout_percentage: number;
        variant: string | null;
        aggregation_group_type_index: number | null;
    }>;
    /**
     * A holdout group — a stable slice of users excluded from experiment exposure.
     */
    export type ExperimentHoldout = {
        id: number;
        /**
         * Human-readable name for the holdout group.
         */
        name: string;
        /**
         * A holdout group — a stable slice of users excluded from experiment exposure.
         */
        description?: (string | null) | undefined;
        /**
         * A holdout group — a stable slice of users excluded from experiment exposure.
         */
        filters?: Array<FeatureFlagConditionGroupSchema> | undefined;
        created_by: UserBasic & unknown;
        created_at: string;
        updated_at: string;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    export type ExperimentParameters = Partial<{
        minimum_detectable_effect: number | null;
        variant_notes: Record<string, string> | null;
    }>;
    export type ManualMetricType = "funnel" | "mean_count" | "mean_sum_or_avg";
    export type ExperimentExposureEstimateConfig = {
        /**
         * 'manual' when the baseline value and exposure rate were entered by hand, 'automatic' when derived from live experiment data.
         */
        conversionRateInputType: ConversionRateInputType;
        manualBaselineValue?: (number | null) | undefined;
        manualExposureRate?: (number | null) | undefined;
        manualMetricType?: (ManualMetricType | null) | undefined;
    };
    export type ExperimentRunningTimeCalculation = Partial<{
        exposure_estimate_config: ExperimentExposureEstimateConfig | null;
        minimum_detectable_effect: number | null;
        recommended_running_time: number | null;
        recommended_sample_size: number | null;
    }>;
    export type ExperimentToSavedMetric = {
        id: number;
        experiment: number;
        saved_metric: number;
        metadata?: unknown | undefined;
        created_at: string;
        query: unknown;
        name: string;
    };
    /**
     * * `web` - web
     * * `product` - product
     */
    export type ExperimentTypeEnum = "web" | "product";
    export type Kind1 = "ExperimentEventExposureConfig" | "ActionsNode";
    export type ExperimentApiExposureConfig = {
        event?: (string | null) | undefined;
        id?: (number | null) | undefined;
        kind?: (Kind1 | null) | undefined;
        /**
         * Property filters (event, person, and other supported types). Pass an empty array if no filters needed.
         */
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        >;
    };
    export type ExperimentApiExposureCriteria = Partial<{
        activation_config: ExperimentApiExposureConfig | null;
        exposure_config: ExperimentApiExposureConfig | null;
        filterTestAccounts: boolean | null;
        multiple_variant_handling: MultipleVariantHandling | null;
    }>;
    export type Kind = "EventsNode" | "ActionsNode";
    export type ExperimentApiEventSource = {
        event?: (string | null) | undefined;
        id?: (number | null) | undefined;
        kind: Kind;
        math?: (ExperimentMetricMathType | null) | undefined;
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        math_hogql?: (string | null) | undefined;
        math_property?: (string | null) | undefined;
        properties?: (Array<EventPropertyFilter> | null) | undefined;
    };
    export type ExperimentMetricType =
        | "funnel"
        | "mean"
        | "ratio"
        | "retention";
    export type ExperimentApiMetric = {
        completion_event?: (ExperimentApiEventSource | null) | undefined;
        conversion_window?: (number | null) | undefined;
        denominator?: (ExperimentApiEventSource | null) | undefined;
        denominator_outlier_handling?:
            | (ExperimentMetricOutlierHandling | null)
            | undefined;
        goal?: (ExperimentMetricGoal | null) | undefined;
        ignore_zeros?: (boolean | null) | undefined;
        kind?: string | undefined;
        lower_bound_percentile?: (number | null) | undefined;
        metric_type: ExperimentMetricType;
        name?: (string | null) | undefined;
        numerator?: (ExperimentApiEventSource | null) | undefined;
        numerator_outlier_handling?:
            | (ExperimentMetricOutlierHandling | null)
            | undefined;
        retention_window_end?: (number | null) | undefined;
        retention_window_start?: (number | null) | undefined;
        retention_window_unit?:
            | (FunnelConversionWindowTimeUnit | null)
            | undefined;
        series?: (Array<ExperimentApiEventSource> | null) | undefined;
        source?: (ExperimentApiEventSource | null) | undefined;
        start_event?: (ExperimentApiEventSource | null) | undefined;
        start_handling?: (StartHandling | null) | undefined;
        threshold?: (number | null) | undefined;
        upper_bound_percentile?: (number | null) | undefined;
        uuid?: (string | null) | undefined;
    };
    /**
     * List wrapper for OpenAPI schema generation — the field stores an array of metrics.
     */
    export type _ExperimentApiMetricsList = Array<ExperimentApiMetric>;
    export type ExperimentStatusEnum =
        | "draft"
        | "running"
        | "paused"
        | "exposure_frozen"
        | "stopped";
    /**
     * Full experiment representation for the detail, create, and update endpoints.
     *
     * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
     * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
     * fields, and refreshes stale action names while serializing. The list endpoint uses the
     * leaner ``ExperimentBasicSerializer`` instead.
     */
    export type Experiment = {
        id: number;
        /**
         * Name of the experiment.
         */
        name: string;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        description?: (string | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        start_date?: (string | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        end_date?: (string | null) | undefined;
        /**
         * Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible.
         */
        feature_flag_key: string;
        feature_flag: MinimalFeatureFlag & unknown;
        holdout: ExperimentHoldout & unknown;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        holdout_id?: (number | null) | undefined;
        exposure_cohort: number | null;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        parameters?: (ExperimentParameters | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        running_time_calculation?:
            | (ExperimentRunningTimeCalculation | null)
            | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        excluded_variants?: (Array<string> | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        secondary_metrics?: unknown | undefined;
        saved_metrics: Array<ExperimentToSavedMetric>;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        saved_metrics_ids?: (Array<unknown> | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        filters?: unknown | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        archived?: boolean | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        deleted?: (boolean | null) | undefined;
        created_by: UserBasic & unknown;
        created_at: string;
        updated_at: string;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        type?: (ExperimentTypeEnum | NullEnum) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        exposure_criteria?: (ExperimentApiExposureCriteria | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        metrics?: (_ExperimentApiMetricsList | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        metrics_secondary?: (_ExperimentApiMetricsList | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        stats_config?: unknown | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        scheduling_config?: unknown | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        allow_unknown_events?: boolean | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        _create_in_folder?: string | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        conclusion?: (ConclusionEnum | NullEnum) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        conclusion_comment?: (string | null) | undefined;
        /**
         * ID of the Desktop task opened to remove the experiment's feature-flag code, when one was requested via open_cleanup_pr on end/ship_variant. Read its status via the flag_cleanup_task action.
         */
        flag_cleanup_task_id: string | null;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        repository?: (string | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        primary_metrics_ordered_uuids?: unknown | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        secondary_metrics_ordered_uuids?: unknown | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        only_count_matured_users?: boolean | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        update_feature_flag_params?: boolean | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        version?: (number | null) | undefined;
        /**
         * Full experiment representation for the detail, create, and update endpoints.
         *
         * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
         * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
         * fields, and refreshes stale action names while serializing. The list endpoint uses the
         * leaner ``ExperimentBasicSerializer`` instead.
         */
        original_experiment?: (Record<string, unknown> | null) | undefined;
        /**
         * Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended).
         */
        status: ExperimentStatusEnum & unknown;
        /**
         * Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project.
         */
        is_legacy: boolean;
        /**
         * Whether enrollment can be frozen right now: the experiment must be running (not draft, paused, stopped, or already frozen) and its feature flag must have release conditions that a person cohort can narrow (no group aggregation, no holdout, no early access conditions).
         */
        can_freeze_exposure: boolean;
        /**
         * The event exposures are actually counted on when the experiment doesn't configure a custom one — `$feature_flag_called`, or `$experiment_exposure` once the team is in the rollout and the experiment started at or after the cutoff. Resolved server-side so clients display the same event the results queries read. For a draft, this is what the experiment would resolve to if launched now.
         */
        resolved_exposure_event: string;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    export type SampleRatioMismatch = {
        expected: Record<string, number>;
        p_value: number;
    };
    export type ExperimentExposureTimeSeries = {
        days: Array<string>;
        exposure_counts: Array<number>;
        variant: string;
    };
    export type ExperimentExposureQueryResponse = {
        bias_risk?: (BiasRisk | null) | undefined;
        date_range: DateRange;
        kind?: string | undefined;
        sample_ratio_mismatch?: (SampleRatioMismatch | null) | undefined;
        timeseries: Array<ExperimentExposureTimeSeries>;
        total_exposures: Record<string, number>;
        warnings?: (Array<DataWarehouseSyncWarning> | null) | undefined;
    };
    /**
     * A single release-condition group carrying only the overall rollout percentage, the one
     * groups entry the experiment input applies.
     */
    export type ExperimentFlagRolloutGroup = Partial<{
        rollout_percentage: number | null;
        properties: Array<unknown>;
    }>;
    /**
     * A single multivariate variant. Extra per-variant keys are dropped.
     */
    export type ExperimentFlagVariant = {
        /**
         * Unique variant key. The baseline defaults to the variant keyed 'control' when present, else the first variant.
         */
        key: string;
        /**
         * A single multivariate variant. Extra per-variant keys are dropped.
         */
        name?: string | undefined;
        /**
         * Variant rollout percentage (0-100). Across variants these must sum to 100.
         */
        rollout_percentage: number;
    };
    /**
     * Multivariate config for the experiment's feature flag.
     */
    export type ExperimentFlagMultivariate = {
        /**
         * Variant definitions (2 to 20). The baseline defaults to the variant keyed 'control' when present, else the first variant.
         */
        variants: Array<ExperimentFlagVariant>;
    };
    /**
     * Feature-flag filters accepted by the experiment endpoints: the flag's own filters shape,
     * minus the keys experiments don't apply.
     */
    export type ExperimentFeatureFlagFilters = Partial<{
        groups: Array<ExperimentFlagRolloutGroup>;
        multivariate: ExperimentFlagMultivariate | null;
        aggregation_group_type_index: number | null;
        payloads: Record<string, string>;
    }>;
    /**
     * Flag config for experiment create/update, sent through the linked feature flag's own shape.
     *
     * Validated both as the OpenAPI request field (via ``ExperimentWriteSerializer``) and at runtime
     * (``ExperimentSerializer._normalize_feature_flag_input`` runs it against the raw feature_flag
     * object). Echoed read-only flag objects (carrying a non-null id) are handled upstream and never
     * reach this validation.
     */
    export type ExperimentFeatureFlagInput = Partial<{
        filters: ExperimentFeatureFlagFilters;
        ensure_experience_continuity: boolean | null;
    }>;
    /**
     * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
     */
    export type ExperimentWrite = {
        id: number;
        /**
         * Name of the experiment.
         */
        name: string;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        description?: (string | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        start_date?: (string | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        end_date?: (string | null) | undefined;
        /**
         * Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible.
         */
        feature_flag_key: string;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        feature_flag?: ExperimentFeatureFlagInput | undefined;
        holdout: ExperimentHoldout & unknown;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        holdout_id?: (number | null) | undefined;
        exposure_cohort: number | null;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        parameters?: (ExperimentParameters | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        running_time_calculation?:
            | (ExperimentRunningTimeCalculation | null)
            | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        excluded_variants?: (Array<string> | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        secondary_metrics?: unknown | undefined;
        saved_metrics: Array<ExperimentToSavedMetric>;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        saved_metrics_ids?: (Array<unknown> | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        filters?: unknown | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        archived?: boolean | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        deleted?: (boolean | null) | undefined;
        created_by: UserBasic & unknown;
        created_at: string;
        updated_at: string;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        type?: (ExperimentTypeEnum | NullEnum) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        exposure_criteria?: (ExperimentApiExposureCriteria | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        metrics?: (_ExperimentApiMetricsList | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        metrics_secondary?: (_ExperimentApiMetricsList | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        stats_config?: unknown | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        scheduling_config?: unknown | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        allow_unknown_events?: boolean | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        _create_in_folder?: string | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        conclusion?: (ConclusionEnum | NullEnum) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        conclusion_comment?: (string | null) | undefined;
        /**
         * ID of the Desktop task opened to remove the experiment's feature-flag code, when one was requested via open_cleanup_pr on end/ship_variant. Read its status via the flag_cleanup_task action.
         */
        flag_cleanup_task_id: string | null;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        repository?: (string | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        primary_metrics_ordered_uuids?: unknown | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        secondary_metrics_ordered_uuids?: unknown | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        only_count_matured_users?: boolean | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        update_feature_flag_params?: boolean | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        version?: (number | null) | undefined;
        /**
         * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
         */
        original_experiment?: (Record<string, unknown> | null) | undefined;
        /**
         * Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended).
         */
        status: ExperimentStatusEnum & unknown;
        /**
         * Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project.
         */
        is_legacy: boolean;
        /**
         * Whether enrollment can be frozen right now: the experiment must be running (not draft, paused, stopped, or already frozen) and its feature flag must have release conditions that a person cohort can narrow (no group aggregation, no holdout, no early access conditions).
         */
        can_freeze_exposure: boolean;
        /**
         * The event exposures are actually counted on when the experiment doesn't configure a custom one — `$feature_flag_called`, or `$experiment_exposure` once the team is in the rollout and the experiment started at or after the cutoff. Resolved server-side so clients display the same event the results queries read. For a draft, this is what the experiment would resolve to if launched now.
         */
        resolved_exposure_event: string;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    /**
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin
     */
    export type ExternalDataSchemaSyncTypeEnum =
        | "full_refresh"
        | "incremental"
        | "append"
        | "webhook"
        | "cdc"
        | "xmin";
    /**
     * * `integer` - integer
     * * `numeric` - numeric
     * * `datetime` - datetime
     * * `date` - date
     * * `timestamp` - timestamp
     * * `objectid` - objectid
     * * `xid` - xid
     */
    export type IncrementalFieldTypeEnum =
        | "integer"
        | "numeric"
        | "datetime"
        | "date"
        | "timestamp"
        | "objectid"
        | "xid";
    /**
     * * `never` - never
     * * `5min` - 5min
     * * `15min` - 15min
     * * `30min` - 30min
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day
     * * `30day` - 30day
     */
    export type ExternalDataSchemaSyncFrequencyEnum =
        | "never"
        | "5min"
        | "15min"
        | "30min"
        | "1hour"
        | "6hour"
        | "12hour"
        | "24hour"
        | "7day"
        | "30day";
    export type ExternalDataSourceApiVersionDeprecation = {
        /**
         * The deprecated vendor API version this source is pinned to.
         */
        version: string;
        /**
         * Date the vendor stops serving this version; null if not announced.
         */
        sunset_at: string | null;
        /**
         * The source's current default vendor API version — the migration target.
         */
        default_version: string;
    };
    /**
     * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
     */
    export type ExternalDataSchema = {
        id: string;
        name: string;
        label: string | null;
        table: Record<string, unknown> | null;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        should_sync?: boolean | undefined;
        last_synced_at: string | null;
        /**
         * The latest error that occurred when syncing this schema.
         */
        latest_error: string | null;
        incremental: boolean;
        status: string | null;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        sync_type?: (ExternalDataSchemaSyncTypeEnum | NullEnum) | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        incremental_field?: (string | null) | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        incremental_field_type?:
            | (IncrementalFieldTypeEnum | NullEnum)
            | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        incremental_field_lookback_seconds?: (number | null) | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        sync_frequency?:
            | (ExternalDataSchemaSyncFrequencyEnum | NullEnum)
            | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        sync_time_of_day?: (string | null) | undefined;
        description: string | null;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        primary_key_columns?: (Array<string> | null) | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        cdc_table_mode?: (CdcTableModeEnum | NullEnum) | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        enabled_columns?: (Array<string> | null) | undefined;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        row_filters?:
            | (Array<{
                  column: string;
                  /**
                   * One of: > >= < <= = != IN "NOT IN".
                   */
                  operator: string;
                  /**
                   * Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`).
                   */
                  value: unknown;
              }> | null)
            | undefined;
        /**
         * Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync/refresh.
         */
        available_columns: Array<{
            name: string;
            data_type?: string | undefined;
            is_nullable?: boolean | undefined;
        }>;
        /**
         * Whether exact source-side column metadata is available for safe source-query projection.
         */
        source_column_metadata_available: boolean;
        /**
         * Lightweight parent-source summary (id, source_type, access_method, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
         */
        source: Partial<{
            id: string;
            source_type: string;
            access_method: string;
            supports_column_selection: boolean;
            supports_row_filters: boolean;
            requires_exact_column_metadata: boolean;
            user_access_level: string | null;
            api_version: string | null;
            supported_api_versions: Array<string>;
        }> | null;
        /**
         * A schema of an external data source: its sync configuration and the warehouse table it syncs into.
         */
        api_version?: (string | null) | undefined;
        /**
         * Set when this schema's version override is deprecated by the vendor; null when there is no override or it is not deprecated. The source-level field covers the source pin.
         */
        api_version_deprecation: ExternalDataSourceApiVersionDeprecation | null;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    /**
     * * `warehouse` - warehouse
     * * `direct` - direct
     */
    export type ExternalDataSourceAccessMethodEnum = "warehouse" | "direct";
    export type ExternalDataSourceBulkUpdateSchema = {
        /**
         * Schema identifier to update.
         */
        id: string;
        should_sync?: boolean | undefined;
        sync_type?: (ExternalDataSchemaSyncTypeEnum | NullEnum) | undefined;
        incremental_field?: (string | null) | undefined;
        incremental_field_type?: (string | null) | undefined;
        sync_frequency?: (string | null) | undefined;
        sync_time_of_day?: (string | null) | undefined;
        primary_key_columns?: (Array<string> | null) | undefined;
        cdc_table_mode?: (CdcTableModeEnum | NullEnum) | undefined;
        enabled_columns?: (Array<string> | null) | undefined;
        row_filters?:
            | (Array<{
                  column: string;
                  /**
                   * One of: > >= < <= = != IN "NOT IN".
                   */
                  operator: string;
                  /**
                   * Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`).
                   */
                  value: unknown;
              }> | null)
            | undefined;
        apply_sync_defaults?: boolean | undefined;
    };
    /**
     * * `Ashby` - Ashby
     * * `Supabase` - Supabase
     * * `CustomerIO` - CustomerIO
     * * `Github` - Github
     * * `Stripe` - Stripe
     * * `Hubspot` - Hubspot
     * * `Postgres` - Postgres
     * * `Zendesk` - Zendesk
     * * `Snowflake` - Snowflake
     * * `Salesforce` - Salesforce
     * * `MySQL` - MySQL
     * * `MongoDB` - MongoDB
     * * `MSSQL` - MSSQL
     * * `Vitally` - Vitally
     * * `BigQuery` - BigQuery
     * * `Chargebee` - Chargebee
     * * `Clerk` - Clerk
     * * `GoogleAds` - GoogleAds
     * * `GoogleSearchConsole` - GoogleSearchConsole
     * * `TemporalIO` - TemporalIO
     * * `DoIt` - DoIt
     * * `GoogleSheets` - GoogleSheets
     * * `MetaAds` - MetaAds
     * * `Klaviyo` - Klaviyo
     * * `Mailchimp` - Mailchimp
     * * `Braze` - Braze
     * * `Mailjet` - Mailjet
     * * `Redshift` - Redshift
     * * `Polar` - Polar
     * * `RevenueCat` - RevenueCat
     * * `LinkedinAds` - LinkedinAds
     * * `RedditAds` - RedditAds
     * * `TikTokAds` - TikTokAds
     * * `BingAds` - BingAds
     * * `Shopify` - Shopify
     * * `Attio` - Attio
     * * `SnapchatAds` - SnapchatAds
     * * `Linear` - Linear
     * * `Intercom` - Intercom
     * * `Amplitude` - Amplitude
     * * `Mixpanel` - Mixpanel
     * * `Jira` - Jira
     * * `ActiveCampaign` - ActiveCampaign
     * * `Marketo` - Marketo
     * * `Adjust` - Adjust
     * * `AppsFlyer` - AppsFlyer
     * * `Freshdesk` - Freshdesk
     * * `GoogleAnalytics` - GoogleAnalytics
     * * `Pipedrive` - Pipedrive
     * * `SendGrid` - SendGrid
     * * `Slack` - Slack
     * * `PagerDuty` - PagerDuty
     * * `Asana` - Asana
     * * `Notion` - Notion
     * * `Airtable` - Airtable
     * * `Greenhouse` - Greenhouse
     * * `BambooHR` - BambooHR
     * * `Lever` - Lever
     * * `GitLab` - GitLab
     * * `Datadog` - Datadog
     * * `Sentry` - Sentry
     * * `Pendo` - Pendo
     * * `FullStory` - FullStory
     * * `AmazonAds` - AmazonAds
     * * `PinterestAds` - PinterestAds
     * * `AppleSearchAds` - AppleSearchAds
     * * `QuickBooks` - QuickBooks
     * * `Xero` - Xero
     * * `NetSuite` - NetSuite
     * * `WooCommerce` - WooCommerce
     * * `BigCommerce` - BigCommerce
     * * `PayPal` - PayPal
     * * `Square` - Square
     * * `Zoom` - Zoom
     * * `Trello` - Trello
     * * `Monday` - Monday
     * * `ClickUp` - ClickUp
     * * `Confluence` - Confluence
     * * `Recurly` - Recurly
     * * `SalesLoft` - SalesLoft
     * * `Outreach` - Outreach
     * * `Gong` - Gong
     * * `Calendly` - Calendly
     * * `Typeform` - Typeform
     * * `Iterable` - Iterable
     * * `ZohoCRM` - ZohoCRM
     * * `Close` - Close
     * * `Oracle` - Oracle
     * * `DynamoDB` - DynamoDB
     * * `Elasticsearch` - Elasticsearch
     * * `Kafka` - Kafka
     * * `LaunchDarkly` - LaunchDarkly
     * * `Braintree` - Braintree
     * * `Recharge` - Recharge
     * * `HelpScout` - HelpScout
     * * `Gorgias` - Gorgias
     * * `Instagram` - Instagram
     * * `YouTubeAnalytics` - YouTubeAnalytics
     * * `FacebookPages` - FacebookPages
     * * `TwitterAds` - TwitterAds
     * * `Workday` - Workday
     * * `ServiceNow` - ServiceNow
     * * `Pardot` - Pardot
     * * `Copper` - Copper
     * * `Front` - Front
     * * `ChartMogul` - ChartMogul
     * * `Zuora` - Zuora
     * * `Paddle` - Paddle
     * * `CircleCI` - CircleCI
     * * `CockroachDB` - CockroachDB
     * * `Firebase` - Firebase
     * * `AzureBlob` - AzureBlob
     * * `GoogleDrive` - GoogleDrive
     * * `OneDrive` - OneDrive
     * * `SharePoint` - SharePoint
     * * `Box` - Box
     * * `SFTP` - SFTP
     * * `MicrosoftTeams` - MicrosoftTeams
     * * `Aircall` - Aircall
     * * `Webflow` - Webflow
     * * `Okta` - Okta
     * * `Auth0` - Auth0
     * * `Productboard` - Productboard
     * * `Smartsheet` - Smartsheet
     * * `Wrike` - Wrike
     * * `Plaid` - Plaid
     * * `SurveyMonkey` - SurveyMonkey
     * * `Eventbrite` - Eventbrite
     * * `RingCentral` - RingCentral
     * * `Twilio` - Twilio
     * * `Freshsales` - Freshsales
     * * `Shortcut` - Shortcut
     * * `ConvertKit` - ConvertKit
     * * `Drip` - Drip
     * * `CampaignMonitor` - CampaignMonitor
     * * `MailerLite` - MailerLite
     * * `Omnisend` - Omnisend
     * * `Brevo` - Brevo
     * * `Postmark` - Postmark
     * * `Granola` - Granola
     * * `BuildBetter` - BuildBetter
     * * `Convex` - Convex
     * * `ClickHouse` - ClickHouse
     * * `Plain` - Plain
     * * `Resend` - Resend
     * * `PgAnalyze` - PgAnalyze
     * * `WorkOS` - WorkOS
     * * `AmazonS3` - AmazonS3
     * * `GoogleCloudStorage` - GoogleCloudStorage
     * * `Databricks` - Databricks
     * * `Dynamics365` - Dynamics365
     * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
     * * `Db2` - Db2
     * * `Heap` - Heap
     * * `AdobeAnalytics` - AdobeAnalytics
     * * `Matomo` - Matomo
     * * `Optimizely` - Optimizely
     * * `Adyen` - Adyen
     * * `GoCardless` - GoCardless
     * * `Mollie` - Mollie
     * * `CheckoutCom` - CheckoutCom
     * * `Branch` - Branch
     * * `Criteo` - Criteo
     * * `Outbrain` - Outbrain
     * * `Taboola` - Taboola
     * * `AdRoll` - AdRoll
     * * `DisplayVideo360` - DisplayVideo360
     * * `GoogleAdManager` - GoogleAdManager
     * * `CampaignManager360` - CampaignManager360
     * * `SearchAds360` - SearchAds360
     * * `AdobeCommerce` - AdobeCommerce
     * * `AmazonSellingPartner` - AmazonSellingPartner
     * * `Ebay` - Ebay
     * * `Commercetools` - Commercetools
     * * `LightspeedRetail` - LightspeedRetail
     * * `Shipmail` - Shipmail
     * * `ShipStation` - ShipStation
     * * `ConstantContact` - ConstantContact
     * * `Mailgun` - Mailgun
     * * `Eloqua` - Eloqua
     * * `Sailthru` - Sailthru
     * * `Ortto` - Ortto
     * * `Attentive` - Attentive
     * * `Kustomer` - Kustomer
     * * `Dixa` - Dixa
     * * `Gladly` - Gladly
     * * `Qualtrics` - Qualtrics
     * * `AzureDevOps` - AzureDevOps
     * * `RoktAds` - RoktAds
     * * `Rollbar` - Rollbar
     * * `Opsgenie` - Opsgenie
     * * `IncidentIo` - IncidentIo
     * * `Pingdom` - Pingdom
     * * `Cloudflare` - Cloudflare
     * * `CosmosDB` - CosmosDB
     * * `PlanetScaleMySQL` - PlanetScaleMySQL
     * * `PlanetScalePostgres` - PlanetScalePostgres
     * * `SapHana` - SapHana
     * * `Rippling` - Rippling
     * * `HiBob` - HiBob
     * * `Personio` - Personio
     * * `Deel` - Deel
     * * `AdpWorkforceNow` - AdpWorkforceNow
     * * `Paylocity` - Paylocity
     * * `Gusto` - Gusto
     * * `CultureAmp` - CultureAmp
     * * `Lattice` - Lattice
     * * `SageIntacct` - SageIntacct
     * * `FreshBooks` - FreshBooks
     * * `Expensify` - Expensify
     * * `Ramp` - Ramp
     * * `Brex` - Brex
     * * `Coupa` - Coupa
     * * `SapConcur` - SapConcur
     * * `Apollo` - Apollo
     * * `Crunchbase` - Crunchbase
     * * `ZoomInfo` - ZoomInfo
     * * `Clari` - Clari
     * * `Chorus` - Chorus
     * * `Coda` - Coda
     * * `Guru` - Guru
     * * `Dropbox` - Dropbox
     * * `Docusign` - Docusign
     * * `PandaDoc` - PandaDoc
     * * `SapErp` - SapErp
     * * `SapSuccessFactors` - SapSuccessFactors
     * * `OracleEbs` - OracleEbs
     * * `OracleFusion` - OracleFusion
     * * `AmazonSNS` - AmazonSNS
     * * `AmazonEventBridge` - AmazonEventBridge
     * * `AmazonSQS` - AmazonSQS
     * * `AmazonKinesis` - AmazonKinesis
     * * `AmazonCloudWatch` - AmazonCloudWatch
     * * `OpenAIAds` - OpenAIAds
     * * `OneHundredMs` - OneHundredMs
     * * `SevenShifts` - SevenShifts
     * * `AcuityScheduling` - AcuityScheduling
     * * `AgileCRM` - AgileCRM
     * * `Aha` - Aha
     * * `Airbyte` - Airbyte
     * * `Akeneo` - Akeneo
     * * `Algolia` - Algolia
     * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
     * * `ApifyDataset` - ApifyDataset
     * * `Appcues` - Appcues
     * * `Appfigures` - Appfigures
     * * `Appfollow` - Appfollow
     * * `Apptivo` - Apptivo
     * * `AssemblyAI` - AssemblyAI
     * * `Awin` - Awin
     * * `AwsCloudTrail` - AwsCloudTrail
     * * `AzureTableStorage` - AzureTableStorage
     * * `Babelforce` - Babelforce
     * * `Basecamp` - Basecamp
     * * `Beamer` - Beamer
     * * `BigMailer` - BigMailer
     * * `Bluetally` - Bluetally
     * * `BoldSign` - BoldSign
     * * `BreezyHR` - BreezyHR
     * * `Bugsnag` - Bugsnag
     * * `Buildkite` - Buildkite
     * * `Bunny` - Bunny
     * * `Buzzsprout` - Buzzsprout
     * * `CalCom` - CalCom
     * * `CallRail` - CallRail
     * * `Campayn` - Campayn
     * * `Canny` - Canny
     * * `CapsuleCRM` - CapsuleCRM
     * * `CaptainData` - CaptainData
     * * `CartCom` - CartCom
     * * `CastorEDC` - CastorEDC
     * * `Chameleon` - Chameleon
     * * `Chargedesk` - Chargedesk
     * * `Chargify` - Chargify
     * * `Chift` - Chift
     * * `Churnkey` - Churnkey
     * * `Cin7` - Cin7
     * * `CiscoMeraki` - CiscoMeraki
     * * `Clazar` - Clazar
     * * `Clockify` - Clockify
     * * `Clockodo` - Clockodo
     * * `Cloudbeds` - Cloudbeds
     * * `Coassemble` - Coassemble
     * * `Codefresh` - Codefresh
     * * `Concord` - Concord
     * * `ConfigCat` - ConfigCat
     * * `Couchbase` - Couchbase
     * * `Curve` - Curve
     * * `Customerly` - Customerly
     * * `Datascope` - Datascope
     * * `Dbt` - Dbt
     * * `Demodesk` - Demodesk
     * * `Deputy` - Deputy
     * * `DevinAI` - DevinAI
     * * `Docuseal` - Docuseal
     * * `Dolibarr` - Dolibarr
     * * `Dremio` - Dremio
     * * `DropboxSign` - DropboxSign
     * * `Dwolla` - Dwolla
     * * `EConomic` - EConomic
     * * `Easypost` - Easypost
     * * `Easypromos` - Easypromos
     * * `Elasticemail` - Elasticemail
     * * `EmailOctopus` - EmailOctopus
     * * `EmploymentHero` - EmploymentHero
     * * `Encharge` - Encharge
     * * `Eventee` - Eventee
     * * `Eventzilla` - Eventzilla
     * * `Everhour` - Everhour
     * * `EZOfficeInventory` - EZOfficeInventory
     * * `Factorial` - Factorial
     * * `Fastbill` - Fastbill
     * * `Fastly` - Fastly
     * * `Fauna` - Fauna
     * * `Feishu` - Feishu
     * * `Fillout` - Fillout
     * * `Finage` - Finage
     * * `Firebolt` - Firebolt
     * * `FireHydrant` - FireHydrant
     * * `Fleetio` - Fleetio
     * * `Flexmail` - Flexmail
     * * `Flexport` - Flexport
     * * `FloatApp` - FloatApp
     * * `Flowlu` - Flowlu
     * * `Formbricks` - Formbricks
     * * `Framer` - Framer
     * * `FreeAgent` - FreeAgent
     * * `Freightview` - Freightview
     * * `Freshcaller` - Freshcaller
     * * `Freshchat` - Freshchat
     * * `Freshservice` - Freshservice
     * * `Fulcrum` - Fulcrum
     * * `GainsightPx` - GainsightPx
     * * `GitBook` - GitBook
     * * `Glassfrog` - Glassfrog
     * * `Goldcast` - Goldcast
     * * `GoLogin` - GoLogin
     * * `Grafana` - Grafana
     * * `GreytHr` - GreytHr
     * * `Gridly` - Gridly
     * * `Harness` - Harness
     * * `Height` - Height
     * * `Hellobaton` - Hellobaton
     * * `HighLevel` - HighLevel
     * * `HoorayHR` - HoorayHR
     * * `Hubplanner` - Hubplanner
     * * `Humanitix` - Humanitix
     * * `Huntr` - Huntr
     * * `Inflowinventory` - Inflowinventory
     * * `InforNexus` - InforNexus
     * * `Insightful` - Insightful
     * * `Insightly` - Insightly
     * * `Instantly` - Instantly
     * * `Instatus` - Instatus
     * * `Intruder` - Intruder
     * * `Invoiced` - Invoiced
     * * `Invoiceninja` - Invoiceninja
     * * `JamfPro` - JamfPro
     * * `JobNimbus` - JobNimbus
     * * `Jotform` - Jotform
     * * `JudgeMeReviews` - JudgeMeReviews
     * * `JustCall` - JustCall
     * * `JustSift` - JustSift
     * * `K6Cloud` - K6Cloud
     * * `Katana` - Katana
     * * `Keka` - Keka
     * * `Kisi` - Kisi
     * * `Kissmetrics` - Kissmetrics
     * * `Klarna` - Klarna
     * * `Klaus` - Klaus
     * * `Lago` - Lago
     * * `Leadfeeder` - Leadfeeder
     * * `Lemlist` - Lemlist
     * * `LessAnnoyingCRM` - LessAnnoyingCRM
     * * `LinkedinPages` - LinkedinPages
     * * `Linkrunner` - Linkrunner
     * * `Linnworks` - Linnworks
     * * `Lob` - Lob
     * * `Lokalise` - Lokalise
     * * `Looker` - Looker
     * * `Luma` - Luma
     * * `MailerSend` - MailerSend
     * * `Mailosaur` - Mailosaur
     * * `Mailtrap` - Mailtrap
     * * `Mantle` - Mantle
     * * `Mention` - Mention
     * * `MercadoAds` - MercadoAds
     * * `Merge` - Merge
     * * `Metabase` - Metabase
     * * `Metricool` - Metricool
     * * `MicrosoftDataverse` - MicrosoftDataverse
     * * `MicrosoftEntraId` - MicrosoftEntraId
     * * `MicrosoftLists` - MicrosoftLists
     * * `Miro` - Miro
     * * `Missive` - Missive
     * * `MixMax` - MixMax
     * * `Mode` - Mode
     * * `Mux` - Mux
     * * `MyHours` - MyHours
     * * `N8n` - N8n
     * * `Navan` - Navan
     * * `NebiusAI` - NebiusAI
     * * `Nexiopay` - Nexiopay
     * * `NinjaOneRMM` - NinjaOneRMM
     * * `NoCRM` - NoCRM
     * * `NorthpassLMS` - NorthpassLMS
     * * `Nutshell` - Nutshell
     * * `Nylas` - Nylas
     * * `Oncehub` - Oncehub
     * * `Onepagecrm` - Onepagecrm
     * * `OneSignal` - OneSignal
     * * `Onfleet` - Onfleet
     * * `OpinionStage` - OpinionStage
     * * `OPUSWatch` - OPUSWatch
     * * `Orb` - Orb
     * * `Orbit` - Orbit
     * * `Oura` - Oura
     * * `Oveit` - Oveit
     * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
     * * `Paperform` - Paperform
     * * `Papersign` - Papersign
     * * `Partnerize` - Partnerize
     * * `PartnerStack` - PartnerStack
     * * `PayFit` - PayFit
     * * `Paystack` - Paystack
     * * `Pennylane` - Pennylane
     * * `Perk` - Perk
     * * `PersistIq` - PersistIq
     * * `Persona` - Persona
     * * `Phyllo` - Phyllo
     * * `Picqer` - Picqer
     * * `Pipeliner` - Pipeliner
     * * `PivotalTracker` - PivotalTracker
     * * `Piwik` - Piwik
     * * `Planhat` - Planhat
     * * `Plausible` - Plausible
     * * `Poplar` - Poplar
     * * `PrestaShop` - PrestaShop
     * * `Pretix` - Pretix
     * * `Primetric` - Primetric
     * * `Printavo` - Printavo
     * * `Printify` - Printify
     * * `Productive` - Productive
     * * `Pylon` - Pylon
     * * `Qonto` - Qonto
     * * `Qualaroo` - Qualaroo
     * * `Railz` - Railz
     * * `RDStationMarketing` - RDStationMarketing
     * * `Recruitee` - Recruitee
     * * `Reddit` - Reddit
     * * `ReferralHero` - ReferralHero
     * * `RentCast` - RentCast
     * * `Repairshopr` - Repairshopr
     * * `ReplyIo` - ReplyIo
     * * `RetailExpress` - RetailExpress
     * * `Retently` - Retently
     * * `RevolutMerchant` - RevolutMerchant
     * * `RocketChat` - RocketChat
     * * `Rocketlane` - Rocketlane
     * * `Rootly` - Rootly
     * * `Ruddr` - Ruddr
     * * `SafetyCulture` - SafetyCulture
     * * `SageHR` - SageHR
     * * `Salesflare` - Salesflare
     * * `SAPFieldglass` - SAPFieldglass
     * * `SavvyCal` - SavvyCal
     * * `Secoda` - Secoda
     * * `Segment` - Segment
     * * `Sendowl` - Sendowl
     * * `SendPulse` - SendPulse
     * * `Senseforce` - Senseforce
     * * `Serpstat` - Serpstat
     * * `Sharetribe` - Sharetribe
     * * `Shippo` - Shippo
     * * `ShopWired` - ShopWired
     * * `Shortio` - Shortio
     * * `Shutterstock` - Shutterstock
     * * `SigmaComputing` - SigmaComputing
     * * `SignNow` - SignNow
     * * `SimpleCast` - SimpleCast
     * * `Simplesat` - Simplesat
     * * `Smaily` - Smaily
     * * `SmartEngage` - SmartEngage
     * * `Smartreach` - Smartreach
     * * `Smartwaiver` - Smartwaiver
     * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
     * * `SonarCloud` - SonarCloud
     * * `SparkPost` - SparkPost
     * * `SplitIo` - SplitIo
     * * `SpotifyAds` - SpotifyAds
     * * `SpotlerCRM` - SpotlerCRM
     * * `Squarespace` - Squarespace
     * * `Statsig` - Statsig
     * * `Statuspage` - Statuspage
     * * `Stigg` - Stigg
     * * `Strava` - Strava
     * * `SurveySparrow` - SurveySparrow
     * * `Survicate` - Survicate
     * * `Svix` - Svix
     * * `Systeme` - Systeme
     * * `Tavus` - Tavus
     * * `Teamtailor` - Teamtailor
     * * `Teamwork` - Teamwork
     * * `Tempo` - Tempo
     * * `Testrail` - Testrail
     * * `Thinkific` - Thinkific
     * * `ThinkificCourses` - ThinkificCourses
     * * `ThriveLearning` - ThriveLearning
     * * `Ticketmaster` - Ticketmaster
     * * `TicketTailor` - TicketTailor
     * * `TickTick` - TickTick
     * * `Timely` - Timely
     * * `Tinyemail` - Tinyemail
     * * `Todoist` - Todoist
     * * `Toggl` - Toggl
     * * `TrackPMS` - TrackPMS
     * * `Tremendous` - Tremendous
     * * `TrustPilot` - TrustPilot
     * * `Twitter` - Twitter
     * * `TyntecSMS` - TyntecSMS
     * * `Unleash` - Unleash
     * * `UpPromote` - UpPromote
     * * `Uptick` - Uptick
     * * `Uservoice` - Uservoice
     * * `Vantage` - Vantage
     * * `Veeqo` - Veeqo
     * * `Vercel` - Vercel
     * * `VismaEconomic` - VismaEconomic
     * * `VWO` - VWO
     * * `Waiteraid` - Waiteraid
     * * `Wasabi` - Wasabi
     * * `WhenIWork` - WhenIWork
     * * `Wordpress` - Wordpress
     * * `Workable` - Workable
     * * `Workflowmax` - Workflowmax
     * * `Workramp` - Workramp
     * * `Wufoo` - Wufoo
     * * `Xsolla` - Xsolla
     * * `YandexMetrica` - YandexMetrica
     * * `Yotpo` - Yotpo
     * * `Ynab` - Ynab
     * * `Younium` - Younium
     * * `YouSign` - YouSign
     * * `YoutubeData` - YoutubeData
     * * `ZapierSupportedStorage` - ZapierSupportedStorage
     * * `ZapSign` - ZapSign
     * * `ZendeskSell` - ZendeskSell
     * * `ZendeskSunshine` - ZendeskSunshine
     * * `Zenefits` - Zenefits
     * * `Zenloop` - Zenloop
     * * `ZohoAnalytics` - ZohoAnalytics
     * * `ZohoBigin` - ZohoBigin
     * * `ZohoBilling` - ZohoBilling
     * * `ZohoBooks` - ZohoBooks
     * * `ZohoCampaign` - ZohoCampaign
     * * `ZohoDesk` - ZohoDesk
     * * `ZohoExpense` - ZohoExpense
     * * `ZohoInventory` - ZohoInventory
     * * `ZohoInvoice` - ZohoInvoice
     * * `ZonkaFeedback` - ZonkaFeedback
     * * `AlphaVantage` - AlphaVantage
     * * `Aviationstack` - Aviationstack
     * * `Bitly` - Bitly
     * * `Blogger` - Blogger
     * * `Breezometer` - Breezometer
     * * `CareQualityCommission` - CareQualityCommission
     * * `Cimis` - Cimis
     * * `CoinApi` - CoinApi
     * * `CoinGecko` - CoinGecko
     * * `CoinMarketCap` - CoinMarketCap
     * * `DingConnect` - DingConnect
     * * `Dockerhub` - Dockerhub
     * * `ExchangeRatesApi` - ExchangeRatesApi
     * * `FinancialModelling` - FinancialModelling
     * * `Finnhub` - Finnhub
     * * `Finnworlds` - Finnworlds
     * * `Giphy` - Giphy
     * * `Gmail` - Gmail
     * * `GNews` - GNews
     * * `GoogleCalendar` - GoogleCalendar
     * * `GoogleClassroom` - GoogleClassroom
     * * `GoogleDirectory` - GoogleDirectory
     * * `GoogleForms` - GoogleForms
     * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
     * * `GoogleTasks` - GoogleTasks
     * * `GoogleWebfonts` - GoogleWebfonts
     * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
     * * `HuggingFace` - HuggingFace
     * * `IlluminaBasespace` - IlluminaBasespace
     * * `Imagga` - Imagga
     * * `Interzoid` - Interzoid
     * * `IP2Whois` - IP2Whois
     * * `KYVE` - KYVE
     * * `Marketstack` - Marketstack
     * * `Mendeley` - Mendeley
     * * `Nasa` - Nasa
     * * `NewYorkTimes` - NewYorkTimes
     * * `NewsApi` - NewsApi
     * * `NewsData` - NewsData
     * * `OpenDataDc` - OpenDataDc
     * * `OpenExchangeRates` - OpenExchangeRates
     * * `OpenAQ` - OpenAQ
     * * `OpenFDA` - OpenFDA
     * * `OpenWeather` - OpenWeather
     * * `Outlook` - Outlook
     * * `Perigon` - Perigon
     * * `Pexels` - Pexels
     * * `Pocket` - Pocket
     * * `Polygon` - Polygon
     * * `PyPI` - PyPI
     * * `Recreation` - Recreation
     * * `RKICovid` - RKICovid
     * * `Rss` - Rss
     * * `SimFin` - SimFin
     * * `StockData` - StockData
     * * `Guardian` - Guardian
     * * `TMDb` - TMDb
     * * `TVMaze` - TVMaze
     * * `TwelveData` - TwelveData
     * * `Ubidots` - Ubidots
     * * `USCensus` - USCensus
     * * `Watchmode` - Watchmode
     * * `WikipediaPageviews` - WikipediaPageviews
     * * `YahooFinance` - YahooFinance
     * * `Clarifai` - Clarifai
     * * `Adapty` - Adapty
     * * `Braintrust` - Braintrust
     * * `StreamElements` - StreamElements
     * * `Streamlabs` - Streamlabs
     * * `Datorama` - Datorama
     * * `Ahrefs` - Ahrefs
     * * `Lightfield` - Lightfield
     * * `Appstack` - Appstack
     * * `Razorpay` - Razorpay
     * * `Neon` - Neon
     * * `NewRelic` - NewRelic
     * * `Custom` - Custom
     * * `Tile38` - Tile38
     * * `Chatwoot` - Chatwoot
     * * `Sanity` - Sanity
     * * `Metronome` - Metronome
     * * `Jobber` - Jobber
     * * `Knock` - Knock
     * * `Leexi` - Leexi
     * * `RB2B` - RB2B
     * * `Superwall` - Superwall
     * * `Liana` - Liana
     * * `TawkTo` - TawkTo
     * * `Hightouch` - Hightouch
     * * `LemonSqueezy` - LemonSqueezy
     * * `Ikas` - Ikas
     * * `Talkwalker` - Talkwalker
     * * `NextdoorAds` - NextdoorAds
     * * `AppLovin` - AppLovin
     * * `Baserow` - Baserow
     * * `Plunk` - Plunk
     * * `Dub` - Dub
     * * `AirOps` - AirOps
     * * `Podium` - Podium
     * * `Loops` - Loops
     * * `Redis` - Redis
     * * `Mercury` - Mercury
     * * `Gojiberry` - Gojiberry
     * * `Teachable` - Teachable
     * * `PeecAI` - PeecAI
     * * `Healthchecks` - Healthchecks
     * * `Impact` - Impact
     * * `AikidoSecurity` - AikidoSecurity
     * * `Alguna` - Alguna
     * * `Anthropic` - Anthropic
     * * `Appwrite` - Appwrite
     * * `BlandAI` - BlandAI
     * * `BrowseAI` - BrowseAI
     * * `BrowserUse` - BrowserUse
     * * `ChartHop` - ChartHop
     * * `Cody` - Cody
     * * `Cursor` - Cursor
     * * `Decagon` - Decagon
     * * `Deepgram` - Deepgram
     * * `ElevenLabs` - ElevenLabs
     * * `Harvey` - Harvey
     * * `Hyperspell` - Hyperspell
     * * `Langfuse` - Langfuse
     * * `LingoDev` - LingoDev
     * * `M3ter` - M3ter
     * * `Maxio` - Maxio
     * * `Metorial` - Metorial
     * * `OpenRouter` - OpenRouter
     * * `TogetherAI` - TogetherAI
     * * `Vapi` - Vapi
     * * `Vespa` - Vespa
     * * `Writesonic` - Writesonic
     * * `Aiven` - Aiven
     * * `Aviator` - Aviator
     * * `Backblaze` - Backblaze
     * * `Baseten` - Baseten
     * * `Browserbase` - Browserbase
     * * `Cohere` - Cohere
     * * `DenoDeploy` - DenoDeploy
     * * `DigitalOcean` - DigitalOcean
     * * `E2B` - E2B
     * * `Fintoc` - Fintoc
     * * `Firecrawl` - Firecrawl
     * * `FireworksAI` - FireworksAI
     * * `FlyIo` - FlyIo
     * * `Groq` - Groq
     * * `GrowthBook` - GrowthBook
     * * `Gumloop` - Gumloop
     * * `Hatchet` - Hatchet
     * * `Helicone` - Helicone
     * * `Heroku` - Heroku
     * * `Hetzner` - Hetzner
     * * `HeyGen` - HeyGen
     * * `Infisical` - Infisical
     * * `Inngest` - Inngest
     * * `KapaAI` - KapaAI
     * * `Kernel` - Kernel
     * * `Koyeb` - Koyeb
     * * `LambdaLabs` - LambdaLabs
     * * `LangSmith` - LangSmith
     * * `Linode` - Linode
     * * `LlamaCloud` - LlamaCloud
     * * `Mem0` - Mem0
     * * `Metriport` - Metriport
     * * `Mintlify` - Mintlify
     * * `MistralAI` - MistralAI
     * * `Mono` - Mono
     * * `Netlify` - Netlify
     * * `Northflank` - Northflank
     * * `OpenAI` - OpenAI
     * * `Pinecone` - Pinecone
     * * `PlatformSh` - PlatformSh
     * * `PromptingCompany` - PromptingCompany
     * * `Qdrant` - Qdrant
     * * `Render` - Render
     * * `Replicate` - Replicate
     * * `RetellAI` - RetellAI
     * * `Roark` - Roark
     * * `RunPod` - RunPod
     * * `ScaleAI` - ScaleAI
     * * `Scaleway` - Scaleway
     * * `SigNoz` - SigNoz
     * * `Sim` - Sim
     * * `Skyvern` - Skyvern
     * * `Slash` - Slash
     * * `Synthesia` - Synthesia
     * * `Telli` - Telli
     * * `TerraApi` - TerraApi
     * * `TriggerDev` - TriggerDev
     * * `Turso` - Turso
     * * `Singular` - Singular
     * * `Swonkie` - Swonkie
     * * `TwelveLabs` - TwelveLabs
     * * `Twenty` - Twenty
     * * `Unstructured` - Unstructured
     * * `Upstash` - Upstash
     * * `Vellum` - Vellum
     * * `Vultr` - Vultr
     * * `Windmill` - Windmill
     * * `Zep` - Zep
     * * `Hex` - Hex
     * * `Sumsub` - Sumsub
     * * `GoogleChat` - GoogleChat
     * * `Kickscale` - Kickscale
     * * `Zellify` - Zellify
     * * `RudderStack` - RudderStack
     * * `DodoPayments` - DodoPayments
     * * `Salestrics` - Salestrics
     * * `Doppler` - Doppler
     * * `Usersnap` - Usersnap
     * * `Asknicely` - Asknicely
     * * `Featurebase` - Featurebase
     * * `Frill` - Frill
     * * `Bettermode` - Bettermode
     * * `Dynatrace` - Dynatrace
     * * `Honeycomb` - Honeycomb
     * * `SumoLogic` - SumoLogic
     * * `LogzIO` - LogzIO
     * * `Coralogix` - Coralogix
     * * `BetterStack` - BetterStack
     * * `Raygun` - Raygun
     * * `Honeybadger` - Honeybadger
     * * `Airbrake` - Airbrake
     * * `Appsignal` - Appsignal
     * * `Appdynamics` - Appdynamics
     * * `Instana` - Instana
     * * `SplunkObservabilityCloud` - SplunkObservabilityCloud
     * * `Uptimerobot` - Uptimerobot
     * * `Statuscake` - Statuscake
     * * `Tailscale` - Tailscale
     * * `Flagsmith` - Flagsmith
     * * `Xmatters` - Xmatters
     * * `Squadcast` - Squadcast
     * * `Zenduty` - Zenduty
     * * `Cronitor` - Cronitor
     * * `Jenkins` - Jenkins
     * * `Bitbucket` - Bitbucket
     * * `Gitea` - Gitea
     * * `Teamcity` - Teamcity
     * * `TravisCI` - TravisCI
     * * `Semaphore` - Semaphore
     * * `CircleciInsights` - CircleciInsights
     * * `OctopusDeploy` - OctopusDeploy
     * * `Sourcegraph` - Sourcegraph
     * * `Bitrise` - Bitrise
     * * `Gerrit` - Gerrit
     * * `TerraformCloud` - TerraformCloud
     * * `PulumiCloud` - PulumiCloud
     * * `Spacelift` - Spacelift
     * * `Railway` - Railway
     * * `Argocd` - Argocd
     * * `PrefectCloud` - PrefectCloud
     * * `DagsterCloud` - DagsterCloud
     * * `Env0` - Env0
     * * `Kubecost` - Kubecost
     * * `Snyk` - Snyk
     * * `Semgrep` - Semgrep
     * * `Veracode` - Veracode
     * * `Checkmarx` - Checkmarx
     * * `Gitguardian` - Gitguardian
     * * `QualysVmdr` - QualysVmdr
     * * `Rapid7Insightvm` - Rapid7Insightvm
     * * `TenableVulnerabilityManagement` - TenableVulnerabilityManagement
     * * `Sentinelone` - Sentinelone
     * * `Lacework` - Lacework
     * * `OrcaSecurity` - OrcaSecurity
     * * `Drata` - Drata
     * * `Secureframe` - Secureframe
     * * `CiscoDuo` - CiscoDuo
     * * `Jumpcloud` - Jumpcloud
     * * `OnePassword` - OnePassword
     * * `Stytch` - Stytch
     * * `Sonarqube` - Sonarqube
     * * `Codecov` - Codecov
     * * `Coveralls` - Coveralls
     * * `Codacy` - Codacy
     * * `Deepsource` - Deepsource
     * * `Linearb` - Linearb
     * * `Jellyfish` - Jellyfish
     * * `Swarmia` - Swarmia
     * * `Packagist` - Packagist
     * * `Nuget` - Nuget
     * * `CratesIO` - CratesIO
     * * `SonatypeNexus` - SonatypeNexus
     * * `JfrogArtifactory` - JfrogArtifactory
     * * `Snowplow` - Snowplow
     * * `WeightsAndBiases` - WeightsAndBiases
     * * `MonteCarlo` - MonteCarlo
     * * `Metaplane` - Metaplane
     * * `Datahub` - Datahub
     * * `ClickhouseCloud` - ClickhouseCloud
     * * `ConfluentCloud` - ConfluentCloud
     * * `KongKonnect` - KongKonnect
     * * `Kandji` - Kandji
     * * `Automox` - Automox
     * * `Autumn` - Autumn
     * * `GetStream` - GetStream
     * * `Octolens` - Octolens
     * * `Kajabi` - Kajabi
     * * `Shopware` - Shopware
     * * `Dubsado` - Dubsado
     * * `Campfire` - Campfire
     * * `PromptWatch` - PromptWatch
     * * `Crisp` - Crisp
     * * `Kommo` - Kommo
     * * `Axiom` - Axiom
     * * `Plivo` - Plivo
     * * `DataForSEO` - DataForSEO
     * * `Sleekplan` - Sleekplan
     * * `AbTasty` - AbTasty
     * * `Ably` - Ably
     * * `AbnormalSecurity` - AbnormalSecurity
     * * `Acast` - Acast
     * * `Acculynx` - Acculynx
     * * `Actionstep` - Actionstep
     * * `Aftership` - Aftership
     * * `AhaIdeas` - AhaIdeas
     * * `AkamaiReporting` - AkamaiReporting
     * * `Alation` - Alation
     * * `Alegra` - Alegra
     * * `Allegro` - Allegro
     * * `AnodotCost` - AnodotCost
     * * `Anomalo` - Anomalo
     * * `Apaleo` - Apaleo
     * * `Apitally` - Apitally
     * * `AppStoreConnect` - AppStoreConnect
     * * `Appdirect` - Appdirect
     * * `Appfolio` - Appfolio
     * * `Arxiv` - Arxiv
     * * `Asaas` - Asaas
     * * `Astronomer` - Astronomer
     * * `Athenahealth` - Athenahealth
     * * `Atlan` - Atlan
     * * `AutodeskConstructionCloud` - AutodeskConstructionCloud
     * * `Avalara` - Avalara
     * * `AwsAthena` - AwsAthena
     * * `AwsBatch` - AwsBatch
     * * `AwsBudgets` - AwsBudgets
     * * `AwsCloudformation` - AwsCloudformation
     * * `AwsComputeOptimizer` - AwsComputeOptimizer
     * * `AwsConfig` - AwsConfig
     * * `AwsConnect` - AwsConnect
     * * `AwsCostAndUsageReport` - AwsCostAndUsageReport
     * * `AwsCostAnomalyDetection` - AwsCostAnomalyDetection
     * * `AwsCostExplorer` - AwsCostExplorer
     * * `AwsGlueDataCatalog` - AwsGlueDataCatalog
     * * `AwsGuardduty` - AwsGuardduty
     * * `AwsHealth` - AwsHealth
     * * `AwsIamAccessAnalyzer` - AwsIamAccessAnalyzer
     * * `AwsInspector` - AwsInspector
     * * `AwsMacie` - AwsMacie
     * * `AwsOrganizations` - AwsOrganizations
     * * `AwsRdsPerformanceInsights` - AwsRdsPerformanceInsights
     * * `AwsSagemaker` - AwsSagemaker
     * * `AwsSavingsPlans` - AwsSavingsPlans
     * * `AwsSecurityHub` - AwsSecurityHub
     * * `AwsSes` - AwsSes
     * * `AwsStepFunctions` - AwsStepFunctions
     * * `AwsSupport` - AwsSupport
     * * `AwsSystemsManager` - AwsSystemsManager
     * * `AwsTrustedAdvisor` - AwsTrustedAdvisor
     * * `AwsWaf` - AwsWaf
     * * `AwsXray` - AwsXray
     * * `AzureActivityLog` - AzureActivityLog
     * * `AzureAdvisor` - AzureAdvisor
     * * `AzureApiManagement` - AzureApiManagement
     * * `AzureApplicationInsights` - AzureApplicationInsights
     * * `AzureCostManagement` - AzureCostManagement
     * * `AzureDataExplorer` - AzureDataExplorer
     * * `AzureDataFactory` - AzureDataFactory
     * * `AzureLogAnalytics` - AzureLogAnalytics
     * * `AzureMonitorAlerts` - AzureMonitorAlerts
     * * `AzureMonitorMetrics` - AzureMonitorMetrics
     * * `AzureOpenaiUsage` - AzureOpenaiUsage
     * * `AzurePolicyInsights` - AzurePolicyInsights
     * * `AzureReservations` - AzureReservations
     * * `AzureResourceGraph` - AzureResourceGraph
     * * `AzureResourceHealth` - AzureResourceHealth
     * * `AzureServiceHealth` - AzureServiceHealth
     * * `AzureSynapse` - AzureSynapse
     * * `BackMarket` - BackMarket
     * * `Beehiiv` - Beehiiv
     * * `Bigeye` - Bigeye
     * * `BillCom` - BillCom
     * * `Billomat` - Billomat
     * * `BingWebmasterTools` - BingWebmasterTools
     * * `Bitwarden` - Bitwarden
     * * `BlackbaudRaisersEdgeNxt` - BlackbaudRaisersEdgeNxt
     * * `BlackboardLearn` - BlackboardLearn
     * * `Bling` - Bling
     * * `Bloomerang` - Bloomerang
     * * `Bluesky` - Bluesky
     * * `BolRetailer` - BolRetailer
     * * `Boulevard` - Boulevard
     * * `Buffer` - Buffer
     * * `Bugherd` - Bugherd
     * * `Buildium` - Buildium
     * * `Buttondown` - Buttondown
     * * `BuyMeACoffee` - BuyMeACoffee
     * * `Calendarific` - Calendarific
     * * `Calibre` - Calibre
     * * `CanvasLms` - CanvasLms
     * * `Captivate` - Captivate
     * * `Cashfree` - Cashfree
     * * `CastAi` - CastAi
     * * `Catchpoint` - Catchpoint
     * * `CdcOpenData` - CdcOpenData
     * * `Census` - Census
     * * `Checkly` - Checkly
     * * `CircleSo` - CircleSo
     * * `Classy` - Classy
     * * `Cleartax` - Cleartax
     * * `Clever` - Clever
     * * `Clevertap` - Clevertap
     * * `Cliniko` - Cliniko
     * * `Clio` - Clio
     * * `Clip` - Clip
     * * `Cloudability` - Cloudability
     * * `Cloudsmith` - Cloudsmith
     * * `Cloudzero` - Cloudzero
     * * `Clover` - Clover
     * * `Codemagic` - Codemagic
     * * `Codescene` - Codescene
     * * `Collibra` - Collibra
     * * `Companycam` - Companycam
     * * `Conekta` - Conekta
     * * `ContaAzul` - ContaAzul
     * * `Contentsquare` - Contentsquare
     * * `Cortex` - Cortex
     * * `Courier` - Courier
     * * `Crossref` - Crossref
     * * `CrowdstrikeFalcon` - CrowdstrikeFalcon
     * * `CubeCloud` - CubeCloud
     * * `D2lBrightspace` - D2lBrightspace
     * * `Dayforce` - Dayforce
     * * `Debugbear` - Debugbear
     * * `Descope` - Descope
     * * `Develocity` - Develocity
     * * `Dialpad` - Dialpad
     * * `Discord` - Discord
     * * `Discourse` - Discourse
     * * `Donorbox` - Donorbox
     * * `Doorloop` - Doorloop
     * * `Dovetail` - Dovetail
     * * `Drchrono` - Drchrono
     * * `Dynamics365BusinessCentral` - Dynamics365BusinessCentral
     * * `EcbDataPortal` - EcbDataPortal
     * * `Emarsys` - Emarsys
     * * `Embrace` - Embrace
     * * `Entsoe` - Entsoe
     * * `Eppo` - Eppo
     * * `Etsy` - Etsy
     * * `Eurostat` - Eurostat
     * * `Faire` - Faire
     * * `FarosAi` - FarosAi
     * * `Fieldpulse` - Fieldpulse
     * * `Fieldwire` - Fieldwire
     * * `Filevine` - Filevine
     * * `Finout` - Finout
     * * `Five9` - Five9
     * * `FlexeraCloudCost` - FlexeraCloudCost
     * * `Flutterwave` - Flutterwave
     * * `Fortnox` - Fortnox
     * * `Fourthwall` - Fourthwall
     * * `Fred` - Fred
     * * `Frontegg` - Frontegg
     * * `FusionAuth` - FusionAuth
     * * `G2` - G2
     * * `Gcore` - Gcore
     * * `GcpApigee` - GcpApigee
     * * `GcpArtifactRegistry` - GcpArtifactRegistry
     * * `GcpBigtable` - GcpBigtable
     * * `GcpChronicle` - GcpChronicle
     * * `GcpCloudAssetInventory` - GcpCloudAssetInventory
     * * `GcpCloudBilling` - GcpCloudBilling
     * * `GcpCloudBuild` - GcpCloudBuild
     * * `GcpCloudDeploy` - GcpCloudDeploy
     * * `GcpCloudDns` - GcpCloudDns
     * * `GcpCloudFunctions` - GcpCloudFunctions
     * * `GcpCloudLogging` - GcpCloudLogging
     * * `GcpCloudMonitoring` - GcpCloudMonitoring
     * * `GcpCloudRun` - GcpCloudRun
     * * `GcpCloudSpanner` - GcpCloudSpanner
     * * `GcpCloudSql` - GcpCloudSql
     * * `GcpCloudTrace` - GcpCloudTrace
     * * `GcpCloudWorkflows` - GcpCloudWorkflows
     * * `GcpComputeEngine` - GcpComputeEngine
     * * `GcpContainerAnalysis` - GcpContainerAnalysis
     * * `GcpDataflow` - GcpDataflow
     * * `GcpDataplex` - GcpDataplex
     * * `GcpDataproc` - GcpDataproc
     * * `GcpErrorReporting` - GcpErrorReporting
     * * `GcpGke` - GcpGke
     * * `GcpPubsub` - GcpPubsub
     * * `GcpRecaptchaEnterprise` - GcpRecaptchaEnterprise
     * * `GcpRecommender` - GcpRecommender
     * * `GcpSecurityCommandCenter` - GcpSecurityCommandCenter
     * * `Gdelt` - Gdelt
     * * `GenesysCloud` - GenesysCloud
     * * `Getdx` - Getdx
     * * `Ghost` - Ghost
     * * `Givebutter` - Givebutter
     * * `Gleif` - Gleif
     * * `GooglePlayConsole` - GooglePlayConsole
     * * `Guesty` - Guesty
     * * `Gumroad` - Gumroad
     * * `HarnessCcm` - HarnessCcm
     * * `HarnessSei` - HarnessSei
     * * `Harvest` - Harvest
     * * `Healthie` - Healthie
     * * `Hitpay` - Hitpay
     * * `Hivebrite` - Hivebrite
     * * `Holded` - Holded
     * * `Hostaway` - Hostaway
     * * `HousecallPro` - HousecallPro
     * * `Humanitec` - Humanitec
     * * `ImfData` - ImfData
     * * `Imperva` - Imperva
     * * `InfluxdbCloud` - InfluxdbCloud
     * * `Iyzico` - Iyzico
     * * `Jobtread` - Jobtread
     * * `Kameleoon` - Kameleoon
     * * `KauflandMarketplace` - KauflandMarketplace
     * * `Kestra` - Kestra
     * * `Kick` - Kick
     * * `Kinde` - Kinde
     * * `Kion` - Kion
     * * `Knowbe4` - Knowbe4
     * * `Komodor` - Komodor
     * * `Labelbox` - Labelbox
     * * `Lawmatics` - Lawmatics
     * * `Learnworlds` - Learnworlds
     * * `LexwareOffice` - LexwareOffice
     * * `Lightdash` - Lightdash
     * * `Lodgify` - Lodgify
     * * `Logicmonitor` - Logicmonitor
     * * `Logrocket` - Logrocket
     * * `LoopReturns` - LoopReturns
     * * `Mastodon` - Mastodon
     * * `Meetup` - Meetup
     * * `Memberful` - Memberful
     * * `MercadoPago` - MercadoPago
     * * `Meteostat` - Meteostat
     * * `Mews` - Mews
     * * `Mezmo` - Mezmo
     * * `Microsoft365UsageReports` - Microsoft365UsageReports
     * * `MicrosoftAdvertising` - MicrosoftAdvertising
     * * `MicrosoftClarity` - MicrosoftClarity
     * * `MicrosoftDefenderCloudApps` - MicrosoftDefenderCloudApps
     * * `MicrosoftDefenderEndpoint` - MicrosoftDefenderEndpoint
     * * `MicrosoftDefenderForCloud` - MicrosoftDefenderForCloud
     * * `MicrosoftIntune` - MicrosoftIntune
     * * `MicrosoftPurview` - MicrosoftPurview
     * * `MicrosoftPurviewAudit` - MicrosoftPurviewAudit
     * * `MicrosoftSentinel` - MicrosoftSentinel
     * * `MicrosoftTeamsCallRecords` - MicrosoftTeamsCallRecords
     * * `Midtrans` - Midtrans
     * * `MightyNetworks` - MightyNetworks
     * * `Mindbody` - Mindbody
     * * `Mirakl` - Mirakl
     * * `Moesif` - Moesif
     * * `Moneybird` - Moneybird
     * * `Moodle` - Moodle
     * * `Motherduck` - Motherduck
     * * `Mycase` - Mycase
     * * `NagerDate` - NagerDate
     * * `NeonCrm` - NeonCrm
     * * `Nexhealth` - Nexhealth
     * * `NoaaCdo` - NoaaCdo
     * * `Nobl9` - Nobl9
     * * `Nolt` - Nolt
     * * `Nops` - Nops
     * * `NpmRegistry` - NpmRegistry
     * * `Oecd` - Oecd
     * * `Okendo` - Okendo
     * * `Omni` - Omni
     * * `Onelogin` - Onelogin
     * * `OpenDental` - OpenDental
     * * `OpenMeteo` - OpenMeteo
     * * `Openalex` - Openalex
     * * `Opencorporates` - Opencorporates
     * * `Openfec` - Openfec
     * * `OpnPayments` - OpnPayments
     * * `Opslevel` - Opslevel
     * * `OttoMarket` - OttoMarket
     * * `Ownerrez` - Ownerrez
     * * `Pagbank` - Pagbank
     * * `Patreon` - Patreon
     * * `Pax8` - Pax8
     * * `Paychex` - Paychex
     * * `Paymob` - Paymob
     * * `Paymongo` - Paymongo
     * * `Phonepe` - Phonepe
     * * `Pike13` - Pike13
     * * `Pingone` - Pingone
     * * `PinterestOrganic` - PinterestOrganic
     * * `PlanningCenter` - PlanningCenter
     * * `PluralsightFlow` - PluralsightFlow
     * * `Podbean` - Podbean
     * * `Postscript` - Postscript
     * * `PowerBiAdmin` - PowerBiAdmin
     * * `Practicepanther` - Practicepanther
     * * `Preset` - Preset
     * * `Procore` - Procore
     * * `Productiv` - Productiv
     * * `ProofpointTap` - ProofpointTap
     * * `Propertyware` - Propertyware
     * * `Pubnub` - Pubnub
     * * `Quay` - Quay
     * * `Raken` - Raken
     * * `RedpandaCloud` - RedpandaCloud
     * * `RentManager` - RentManager
     * * `Reverb` - Reverb
     * * `RocketMatter` - RocketMatter
     * * `Rubygems` - Rubygems
     * * `Scalr` - Scalr
     * * `SecEdgar` - SecEdgar
     * * `SelectStar` - SelectStar
     * * `SemanticScholar` - SemanticScholar
     * * `Semrush` - Semrush
     * * `ServiceFusion` - ServiceFusion
     * * `Servicem8` - Servicem8
     * * `Servicetitan` - Servicetitan
     * * `Servicetrade` - Servicetrade
     * * `Sevdesk` - Sevdesk
     * * `Similarweb` - Similarweb
     * * `Simpro` - Simpro
     * * `Sinch` - Sinch
     * * `Singlestore` - Singlestore
     * * `Site24x7` - Site24x7
     * * `Sleuth` - Sleuth
     * * `Smartlook` - Smartlook
     * * `Smartrecruiters` - Smartrecruiters
     * * `Smokeball` - Smokeball
     * * `SodaCloud` - SodaCloud
     * * `Speedcurve` - Speedcurve
     * * `SpotIo` - SpotIo
     * * `Sprig` - Sprig
     * * `Sprinklr` - Sprinklr
     * * `SproutSocial` - SproutSocial
     * * `StackOverflowForTeams` - StackOverflowForTeams
     * * `Stockx` - Stockx
     * * `TackleIo` - TackleIo
     * * `Talkdesk` - Talkdesk
     * * `TeamupFitness` - TeamupFitness
     * * `Tebra` - Tebra
     * * `Telnyx` - Telnyx
     * * `Ternary` - Ternary
     * * `Thoughtspot` - Thoughtspot
     * * `Thousandeyes` - Thousandeyes
     * * `Threads` - Threads
     * * `TiktokShop` - TiktokShop
     * * `TinyErp` - TinyErp
     * * `Tinybird` - Tinybird
     * * `Tipalti` - Tipalti
     * * `Toast` - Toast
     * * `Torii` - Torii
     * * `Transistor` - Transistor
     * * `TrunkIo` - TrunkIo
     * * `Trustradius` - Trustradius
     * * `Twitch` - Twitch
     * * `TwoC2p` - TwoC2p
     * * `UkCompaniesHouse` - UkCompaniesHouse
     * * `UkOns` - UkOns
     * * `UnComtrade` - UnComtrade
     * * `UsBea` - UsBea
     * * `UsBls` - UsBls
     * * `UsEia` - UsEia
     * * `UsTreasuryFiscalData` - UsTreasuryFiscalData
     * * `Vanta` - Vanta
     * * `Vendr` - Vendr
     * * `Virtuous` - Virtuous
     * * `Vonage` - Vonage
     * * `WalmartMarketplace` - WalmartMarketplace
     * * `Waydev` - Waydev
     * * `Wayfair` - Wayfair
     * * `WhatsappBusinessManagement` - WhatsappBusinessManagement
     * * `WhoGho` - WhoGho
     * * `Whop` - Whop
     * * `Wiz` - Wiz
     * * `Wompi` - Wompi
     * * `Workiz` - Workiz
     * * `WorldBank` - WorldBank
     * * `Xendit` - Xendit
     * * `Yoco` - Yoco
     * * `ZalandoZdirect` - ZalandoZdirect
     * * `Zluri` - Zluri
     * * `Zylo` - Zylo
     * * `Tally` - Tally
     * * `Nuntly` - Nuntly
     * * `Vturb` - Vturb
     * * `Meltwater` - Meltwater
     * * `UserCom` - UserCom
     * * `Latitude` - Latitude
     * * `Workato` - Workato
     * * `SideShift` - SideShift
     * * `DuckLake` - DuckLake
     * * `Starburst` - Starburst
     * * `Trino` - Trino
     * * `Easybill` - Easybill
     * * `Bexio` - Bexio
     * * `Umami` - Umami
     * * `Manychat` - Manychat
     * * `Kickstarter` - Kickstarter
     * * `Typesense` - Typesense
     * * `FirstPromoter` - FirstPromoter
     * * `Zero` - Zero
     * * `Inth` - Inth
     * * `BCMS` - BCMS
     * * `Convonite` - Convonite
     * * `Hookdeck` - Hookdeck
     * * `Billit` - Billit
     * * `Moxie` - Moxie
     * * `TripleWhale` - TripleWhale
     * * `Directus` - Directus
     * * `Clay` - Clay
     * * `TradableBits` - TradableBits
     * * `Swan` - Swan
     * * `Hyros` - Hyros
     * * `Odoo` - Odoo
     * * `Airbridge` - Airbridge
     * * `Snovio` - Snovio
     * * `GoogleMerchantCenter` - GoogleMerchantCenter
     * * `Raisely` - Raisely
     * * `RakutenAdvertising` - RakutenAdvertising
     * * `Zitadel` - Zitadel
     * * `DeelFlows` - DeelFlows
     * * `WindsorAi` - WindsorAi
     * * `Wix` - Wix
     * * `Sevalla` - Sevalla
     * * `Motion` - Motion
     * * `ImpactPartner` - ImpactPartner
     * * `Cloudinary` - Cloudinary
     * * `Uploadcare` - Uploadcare
     * * `WHMCS` - WHMCS
     * * `MSG91` - MSG91
     * * `Depot` - Depot
     * * `Schematic` - Schematic
     * * `Dokploy` - Dokploy
     * * `Hootsuite` - Hootsuite
     * * `WisprFlow` - WisprFlow
     * * `SamCart` - SamCart
     * * `IronSourceAds` - IronSourceAds
     * * `MicrosoftExcel` - MicrosoftExcel
     * * `Profound` - Profound
     * * `Airwallex` - Airwallex
     * * `Polymarket` - Polymarket
     * * `Kalshi` - Kalshi
     * * `Capterra` - Capterra
     * * `GooglePostmasterTools` - GooglePostmasterTools
     * * `Growi` - Growi
     * * `Clarify` - Clarify
     * * `DatoCMS` - DatoCMS
     * * `WPSOffice` - WPSOffice
     * * `TeraBox` - TeraBox
     * * `SimonData` - SimonData
     * * `CommissionJunction` - CommissionJunction
     * * `Liveblocks` - Liveblocks
     * * `NationBuilder` - NationBuilder
     * * `Tana` - Tana
     * * `Zenchef` - Zenchef
     * * `Lovable` - Lovable
     * * `Anvil` - Anvil
     * * `Coolify` - Coolify
     * * `SocialPilot` - SocialPilot
     * * `Strato` - Strato
     * * `Medusa` - Medusa
     * * `Membrain` - Membrain
     * * `RecallAI` - RecallAI
     */
    export type ExternalDataSourceTypeEnum =
        | "Ashby"
        | "Supabase"
        | "CustomerIO"
        | "Github"
        | "Stripe"
        | "Hubspot"
        | "Postgres"
        | "Zendesk"
        | "Snowflake"
        | "Salesforce"
        | "MySQL"
        | "MongoDB"
        | "MSSQL"
        | "Vitally"
        | "BigQuery"
        | "Chargebee"
        | "Clerk"
        | "GoogleAds"
        | "GoogleSearchConsole"
        | "TemporalIO"
        | "DoIt"
        | "GoogleSheets"
        | "MetaAds"
        | "Klaviyo"
        | "Mailchimp"
        | "Braze"
        | "Mailjet"
        | "Redshift"
        | "Polar"
        | "RevenueCat"
        | "LinkedinAds"
        | "RedditAds"
        | "TikTokAds"
        | "BingAds"
        | "Shopify"
        | "Attio"
        | "SnapchatAds"
        | "Linear"
        | "Intercom"
        | "Amplitude"
        | "Mixpanel"
        | "Jira"
        | "ActiveCampaign"
        | "Marketo"
        | "Adjust"
        | "AppsFlyer"
        | "Freshdesk"
        | "GoogleAnalytics"
        | "Pipedrive"
        | "SendGrid"
        | "Slack"
        | "PagerDuty"
        | "Asana"
        | "Notion"
        | "Airtable"
        | "Greenhouse"
        | "BambooHR"
        | "Lever"
        | "GitLab"
        | "Datadog"
        | "Sentry"
        | "Pendo"
        | "FullStory"
        | "AmazonAds"
        | "PinterestAds"
        | "AppleSearchAds"
        | "QuickBooks"
        | "Xero"
        | "NetSuite"
        | "WooCommerce"
        | "BigCommerce"
        | "PayPal"
        | "Square"
        | "Zoom"
        | "Trello"
        | "Monday"
        | "ClickUp"
        | "Confluence"
        | "Recurly"
        | "SalesLoft"
        | "Outreach"
        | "Gong"
        | "Calendly"
        | "Typeform"
        | "Iterable"
        | "ZohoCRM"
        | "Close"
        | "Oracle"
        | "DynamoDB"
        | "Elasticsearch"
        | "Kafka"
        | "LaunchDarkly"
        | "Braintree"
        | "Recharge"
        | "HelpScout"
        | "Gorgias"
        | "Instagram"
        | "YouTubeAnalytics"
        | "FacebookPages"
        | "TwitterAds"
        | "Workday"
        | "ServiceNow"
        | "Pardot"
        | "Copper"
        | "Front"
        | "ChartMogul"
        | "Zuora"
        | "Paddle"
        | "CircleCI"
        | "CockroachDB"
        | "Firebase"
        | "AzureBlob"
        | "GoogleDrive"
        | "OneDrive"
        | "SharePoint"
        | "Box"
        | "SFTP"
        | "MicrosoftTeams"
        | "Aircall"
        | "Webflow"
        | "Okta"
        | "Auth0"
        | "Productboard"
        | "Smartsheet"
        | "Wrike"
        | "Plaid"
        | "SurveyMonkey"
        | "Eventbrite"
        | "RingCentral"
        | "Twilio"
        | "Freshsales"
        | "Shortcut"
        | "ConvertKit"
        | "Drip"
        | "CampaignMonitor"
        | "MailerLite"
        | "Omnisend"
        | "Brevo"
        | "Postmark"
        | "Granola"
        | "BuildBetter"
        | "Convex"
        | "ClickHouse"
        | "Plain"
        | "Resend"
        | "PgAnalyze"
        | "WorkOS"
        | "AmazonS3"
        | "GoogleCloudStorage"
        | "Databricks"
        | "Dynamics365"
        | "SalesforceMarketingCloud"
        | "Db2"
        | "Heap"
        | "AdobeAnalytics"
        | "Matomo"
        | "Optimizely"
        | "Adyen"
        | "GoCardless"
        | "Mollie"
        | "CheckoutCom"
        | "Branch"
        | "Criteo"
        | "Outbrain"
        | "Taboola"
        | "AdRoll"
        | "DisplayVideo360"
        | "GoogleAdManager"
        | "CampaignManager360"
        | "SearchAds360"
        | "AdobeCommerce"
        | "AmazonSellingPartner"
        | "Ebay"
        | "Commercetools"
        | "LightspeedRetail"
        | "Shipmail"
        | "ShipStation"
        | "ConstantContact"
        | "Mailgun"
        | "Eloqua"
        | "Sailthru"
        | "Ortto"
        | "Attentive"
        | "Kustomer"
        | "Dixa"
        | "Gladly"
        | "Qualtrics"
        | "AzureDevOps"
        | "RoktAds"
        | "Rollbar"
        | "Opsgenie"
        | "IncidentIo"
        | "Pingdom"
        | "Cloudflare"
        | "CosmosDB"
        | "PlanetScaleMySQL"
        | "PlanetScalePostgres"
        | "SapHana"
        | "Rippling"
        | "HiBob"
        | "Personio"
        | "Deel"
        | "AdpWorkforceNow"
        | "Paylocity"
        | "Gusto"
        | "CultureAmp"
        | "Lattice"
        | "SageIntacct"
        | "FreshBooks"
        | "Expensify"
        | "Ramp"
        | "Brex"
        | "Coupa"
        | "SapConcur"
        | "Apollo"
        | "Crunchbase"
        | "ZoomInfo"
        | "Clari"
        | "Chorus"
        | "Coda"
        | "Guru"
        | "Dropbox"
        | "Docusign"
        | "PandaDoc"
        | "SapErp"
        | "SapSuccessFactors"
        | "OracleEbs"
        | "OracleFusion"
        | "AmazonSNS"
        | "AmazonEventBridge"
        | "AmazonSQS"
        | "AmazonKinesis"
        | "AmazonCloudWatch"
        | "OpenAIAds"
        | "OneHundredMs"
        | "SevenShifts"
        | "AcuityScheduling"
        | "AgileCRM"
        | "Aha"
        | "Airbyte"
        | "Akeneo"
        | "Algolia"
        | "AlpacaBrokerAPI"
        | "ApifyDataset"
        | "Appcues"
        | "Appfigures"
        | "Appfollow"
        | "Apptivo"
        | "AssemblyAI"
        | "Awin"
        | "AwsCloudTrail"
        | "AzureTableStorage"
        | "Babelforce"
        | "Basecamp"
        | "Beamer"
        | "BigMailer"
        | "Bluetally"
        | "BoldSign"
        | "BreezyHR"
        | "Bugsnag"
        | "Buildkite"
        | "Bunny"
        | "Buzzsprout"
        | "CalCom"
        | "CallRail"
        | "Campayn"
        | "Canny"
        | "CapsuleCRM"
        | "CaptainData"
        | "CartCom"
        | "CastorEDC"
        | "Chameleon"
        | "Chargedesk"
        | "Chargify"
        | "Chift"
        | "Churnkey"
        | "Cin7"
        | "CiscoMeraki"
        | "Clazar"
        | "Clockify"
        | "Clockodo"
        | "Cloudbeds"
        | "Coassemble"
        | "Codefresh"
        | "Concord"
        | "ConfigCat"
        | "Couchbase"
        | "Curve"
        | "Customerly"
        | "Datascope"
        | "Dbt"
        | "Demodesk"
        | "Deputy"
        | "DevinAI"
        | "Docuseal"
        | "Dolibarr"
        | "Dremio"
        | "DropboxSign"
        | "Dwolla"
        | "EConomic"
        | "Easypost"
        | "Easypromos"
        | "Elasticemail"
        | "EmailOctopus"
        | "EmploymentHero"
        | "Encharge"
        | "Eventee"
        | "Eventzilla"
        | "Everhour"
        | "EZOfficeInventory"
        | "Factorial"
        | "Fastbill"
        | "Fastly"
        | "Fauna"
        | "Feishu"
        | "Fillout"
        | "Finage"
        | "Firebolt"
        | "FireHydrant"
        | "Fleetio"
        | "Flexmail"
        | "Flexport"
        | "FloatApp"
        | "Flowlu"
        | "Formbricks"
        | "Framer"
        | "FreeAgent"
        | "Freightview"
        | "Freshcaller"
        | "Freshchat"
        | "Freshservice"
        | "Fulcrum"
        | "GainsightPx"
        | "GitBook"
        | "Glassfrog"
        | "Goldcast"
        | "GoLogin"
        | "Grafana"
        | "GreytHr"
        | "Gridly"
        | "Harness"
        | "Height"
        | "Hellobaton"
        | "HighLevel"
        | "HoorayHR"
        | "Hubplanner"
        | "Humanitix"
        | "Huntr"
        | "Inflowinventory"
        | "InforNexus"
        | "Insightful"
        | "Insightly"
        | "Instantly"
        | "Instatus"
        | "Intruder"
        | "Invoiced"
        | "Invoiceninja"
        | "JamfPro"
        | "JobNimbus"
        | "Jotform"
        | "JudgeMeReviews"
        | "JustCall"
        | "JustSift"
        | "K6Cloud"
        | "Katana"
        | "Keka"
        | "Kisi"
        | "Kissmetrics"
        | "Klarna"
        | "Klaus"
        | "Lago"
        | "Leadfeeder"
        | "Lemlist"
        | "LessAnnoyingCRM"
        | "LinkedinPages"
        | "Linkrunner"
        | "Linnworks"
        | "Lob"
        | "Lokalise"
        | "Looker"
        | "Luma"
        | "MailerSend"
        | "Mailosaur"
        | "Mailtrap"
        | "Mantle"
        | "Mention"
        | "MercadoAds"
        | "Merge"
        | "Metabase"
        | "Metricool"
        | "MicrosoftDataverse"
        | "MicrosoftEntraId"
        | "MicrosoftLists"
        | "Miro"
        | "Missive"
        | "MixMax"
        | "Mode"
        | "Mux"
        | "MyHours"
        | "N8n"
        | "Navan"
        | "NebiusAI"
        | "Nexiopay"
        | "NinjaOneRMM"
        | "NoCRM"
        | "NorthpassLMS"
        | "Nutshell"
        | "Nylas"
        | "Oncehub"
        | "Onepagecrm"
        | "OneSignal"
        | "Onfleet"
        | "OpinionStage"
        | "OPUSWatch"
        | "Orb"
        | "Orbit"
        | "Oura"
        | "Oveit"
        | "PabblySubscriptionsBilling"
        | "Paperform"
        | "Papersign"
        | "Partnerize"
        | "PartnerStack"
        | "PayFit"
        | "Paystack"
        | "Pennylane"
        | "Perk"
        | "PersistIq"
        | "Persona"
        | "Phyllo"
        | "Picqer"
        | "Pipeliner"
        | "PivotalTracker"
        | "Piwik"
        | "Planhat"
        | "Plausible"
        | "Poplar"
        | "PrestaShop"
        | "Pretix"
        | "Primetric"
        | "Printavo"
        | "Printify"
        | "Productive"
        | "Pylon"
        | "Qonto"
        | "Qualaroo"
        | "Railz"
        | "RDStationMarketing"
        | "Recruitee"
        | "Reddit"
        | "ReferralHero"
        | "RentCast"
        | "Repairshopr"
        | "ReplyIo"
        | "RetailExpress"
        | "Retently"
        | "RevolutMerchant"
        | "RocketChat"
        | "Rocketlane"
        | "Rootly"
        | "Ruddr"
        | "SafetyCulture"
        | "SageHR"
        | "Salesflare"
        | "SAPFieldglass"
        | "SavvyCal"
        | "Secoda"
        | "Segment"
        | "Sendowl"
        | "SendPulse"
        | "Senseforce"
        | "Serpstat"
        | "Sharetribe"
        | "Shippo"
        | "ShopWired"
        | "Shortio"
        | "Shutterstock"
        | "SigmaComputing"
        | "SignNow"
        | "SimpleCast"
        | "Simplesat"
        | "Smaily"
        | "SmartEngage"
        | "Smartreach"
        | "Smartwaiver"
        | "SolarwindsServiceDesk"
        | "SonarCloud"
        | "SparkPost"
        | "SplitIo"
        | "SpotifyAds"
        | "SpotlerCRM"
        | "Squarespace"
        | "Statsig"
        | "Statuspage"
        | "Stigg"
        | "Strava"
        | "SurveySparrow"
        | "Survicate"
        | "Svix"
        | "Systeme"
        | "Tavus"
        | "Teamtailor"
        | "Teamwork"
        | "Tempo"
        | "Testrail"
        | "Thinkific"
        | "ThinkificCourses"
        | "ThriveLearning"
        | "Ticketmaster"
        | "TicketTailor"
        | "TickTick"
        | "Timely"
        | "Tinyemail"
        | "Todoist"
        | "Toggl"
        | "TrackPMS"
        | "Tremendous"
        | "TrustPilot"
        | "Twitter"
        | "TyntecSMS"
        | "Unleash"
        | "UpPromote"
        | "Uptick"
        | "Uservoice"
        | "Vantage"
        | "Veeqo"
        | "Vercel"
        | "VismaEconomic"
        | "VWO"
        | "Waiteraid"
        | "Wasabi"
        | "WhenIWork"
        | "Wordpress"
        | "Workable"
        | "Workflowmax"
        | "Workramp"
        | "Wufoo"
        | "Xsolla"
        | "YandexMetrica"
        | "Yotpo"
        | "Ynab"
        | "Younium"
        | "YouSign"
        | "YoutubeData"
        | "ZapierSupportedStorage"
        | "ZapSign"
        | "ZendeskSell"
        | "ZendeskSunshine"
        | "Zenefits"
        | "Zenloop"
        | "ZohoAnalytics"
        | "ZohoBigin"
        | "ZohoBilling"
        | "ZohoBooks"
        | "ZohoCampaign"
        | "ZohoDesk"
        | "ZohoExpense"
        | "ZohoInventory"
        | "ZohoInvoice"
        | "ZonkaFeedback"
        | "AlphaVantage"
        | "Aviationstack"
        | "Bitly"
        | "Blogger"
        | "Breezometer"
        | "CareQualityCommission"
        | "Cimis"
        | "CoinApi"
        | "CoinGecko"
        | "CoinMarketCap"
        | "DingConnect"
        | "Dockerhub"
        | "ExchangeRatesApi"
        | "FinancialModelling"
        | "Finnhub"
        | "Finnworlds"
        | "Giphy"
        | "Gmail"
        | "GNews"
        | "GoogleCalendar"
        | "GoogleClassroom"
        | "GoogleDirectory"
        | "GoogleForms"
        | "GooglePageSpeedInsights"
        | "GoogleTasks"
        | "GoogleWebfonts"
        | "GoogleWorkspaceAdminReports"
        | "HuggingFace"
        | "IlluminaBasespace"
        | "Imagga"
        | "Interzoid"
        | "IP2Whois"
        | "KYVE"
        | "Marketstack"
        | "Mendeley"
        | "Nasa"
        | "NewYorkTimes"
        | "NewsApi"
        | "NewsData"
        | "OpenDataDc"
        | "OpenExchangeRates"
        | "OpenAQ"
        | "OpenFDA"
        | "OpenWeather"
        | "Outlook"
        | "Perigon"
        | "Pexels"
        | "Pocket"
        | "Polygon"
        | "PyPI"
        | "Recreation"
        | "RKICovid"
        | "Rss"
        | "SimFin"
        | "StockData"
        | "Guardian"
        | "TMDb"
        | "TVMaze"
        | "TwelveData"
        | "Ubidots"
        | "USCensus"
        | "Watchmode"
        | "WikipediaPageviews"
        | "YahooFinance"
        | "Clarifai"
        | "Adapty"
        | "Braintrust"
        | "StreamElements"
        | "Streamlabs"
        | "Datorama"
        | "Ahrefs"
        | "Lightfield"
        | "Appstack"
        | "Razorpay"
        | "Neon"
        | "NewRelic"
        | "Custom"
        | "Tile38"
        | "Chatwoot"
        | "Sanity"
        | "Metronome"
        | "Jobber"
        | "Knock"
        | "Leexi"
        | "RB2B"
        | "Superwall"
        | "Liana"
        | "TawkTo"
        | "Hightouch"
        | "LemonSqueezy"
        | "Ikas"
        | "Talkwalker"
        | "NextdoorAds"
        | "AppLovin"
        | "Baserow"
        | "Plunk"
        | "Dub"
        | "AirOps"
        | "Podium"
        | "Loops"
        | "Redis"
        | "Mercury"
        | "Gojiberry"
        | "Teachable"
        | "PeecAI"
        | "Healthchecks"
        | "Impact"
        | "AikidoSecurity"
        | "Alguna"
        | "Anthropic"
        | "Appwrite"
        | "BlandAI"
        | "BrowseAI"
        | "BrowserUse"
        | "ChartHop"
        | "Cody"
        | "Cursor"
        | "Decagon"
        | "Deepgram"
        | "ElevenLabs"
        | "Harvey"
        | "Hyperspell"
        | "Langfuse"
        | "LingoDev"
        | "M3ter"
        | "Maxio"
        | "Metorial"
        | "OpenRouter"
        | "TogetherAI"
        | "Vapi"
        | "Vespa"
        | "Writesonic"
        | "Aiven"
        | "Aviator"
        | "Backblaze"
        | "Baseten"
        | "Browserbase"
        | "Cohere"
        | "DenoDeploy"
        | "DigitalOcean"
        | "E2B"
        | "Fintoc"
        | "Firecrawl"
        | "FireworksAI"
        | "FlyIo"
        | "Groq"
        | "GrowthBook"
        | "Gumloop"
        | "Hatchet"
        | "Helicone"
        | "Heroku"
        | "Hetzner"
        | "HeyGen"
        | "Infisical"
        | "Inngest"
        | "KapaAI"
        | "Kernel"
        | "Koyeb"
        | "LambdaLabs"
        | "LangSmith"
        | "Linode"
        | "LlamaCloud"
        | "Mem0"
        | "Metriport"
        | "Mintlify"
        | "MistralAI"
        | "Mono"
        | "Netlify"
        | "Northflank"
        | "OpenAI"
        | "Pinecone"
        | "PlatformSh"
        | "PromptingCompany"
        | "Qdrant"
        | "Render"
        | "Replicate"
        | "RetellAI"
        | "Roark"
        | "RunPod"
        | "ScaleAI"
        | "Scaleway"
        | "SigNoz"
        | "Sim"
        | "Skyvern"
        | "Slash"
        | "Synthesia"
        | "Telli"
        | "TerraApi"
        | "TriggerDev"
        | "Turso"
        | "Singular"
        | "Swonkie"
        | "TwelveLabs"
        | "Twenty"
        | "Unstructured"
        | "Upstash"
        | "Vellum"
        | "Vultr"
        | "Windmill"
        | "Zep"
        | "Hex"
        | "Sumsub"
        | "GoogleChat"
        | "Kickscale"
        | "Zellify"
        | "RudderStack"
        | "DodoPayments"
        | "Salestrics"
        | "Doppler"
        | "Usersnap"
        | "Asknicely"
        | "Featurebase"
        | "Frill"
        | "Bettermode"
        | "Dynatrace"
        | "Honeycomb"
        | "SumoLogic"
        | "LogzIO"
        | "Coralogix"
        | "BetterStack"
        | "Raygun"
        | "Honeybadger"
        | "Airbrake"
        | "Appsignal"
        | "Appdynamics"
        | "Instana"
        | "SplunkObservabilityCloud"
        | "Uptimerobot"
        | "Statuscake"
        | "Tailscale"
        | "Flagsmith"
        | "Xmatters"
        | "Squadcast"
        | "Zenduty"
        | "Cronitor"
        | "Jenkins"
        | "Bitbucket"
        | "Gitea"
        | "Teamcity"
        | "TravisCI"
        | "Semaphore"
        | "CircleciInsights"
        | "OctopusDeploy"
        | "Sourcegraph"
        | "Bitrise"
        | "Gerrit"
        | "TerraformCloud"
        | "PulumiCloud"
        | "Spacelift"
        | "Railway"
        | "Argocd"
        | "PrefectCloud"
        | "DagsterCloud"
        | "Env0"
        | "Kubecost"
        | "Snyk"
        | "Semgrep"
        | "Veracode"
        | "Checkmarx"
        | "Gitguardian"
        | "QualysVmdr"
        | "Rapid7Insightvm"
        | "TenableVulnerabilityManagement"
        | "Sentinelone"
        | "Lacework"
        | "OrcaSecurity"
        | "Drata"
        | "Secureframe"
        | "CiscoDuo"
        | "Jumpcloud"
        | "OnePassword"
        | "Stytch"
        | "Sonarqube"
        | "Codecov"
        | "Coveralls"
        | "Codacy"
        | "Deepsource"
        | "Linearb"
        | "Jellyfish"
        | "Swarmia"
        | "Packagist"
        | "Nuget"
        | "CratesIO"
        | "SonatypeNexus"
        | "JfrogArtifactory"
        | "Snowplow"
        | "WeightsAndBiases"
        | "MonteCarlo"
        | "Metaplane"
        | "Datahub"
        | "ClickhouseCloud"
        | "ConfluentCloud"
        | "KongKonnect"
        | "Kandji"
        | "Automox"
        | "Autumn"
        | "GetStream"
        | "Octolens"
        | "Kajabi"
        | "Shopware"
        | "Dubsado"
        | "Campfire"
        | "PromptWatch"
        | "Crisp"
        | "Kommo"
        | "Axiom"
        | "Plivo"
        | "DataForSEO"
        | "Sleekplan"
        | "AbTasty"
        | "Ably"
        | "AbnormalSecurity"
        | "Acast"
        | "Acculynx"
        | "Actionstep"
        | "Aftership"
        | "AhaIdeas"
        | "AkamaiReporting"
        | "Alation"
        | "Alegra"
        | "Allegro"
        | "AnodotCost"
        | "Anomalo"
        | "Apaleo"
        | "Apitally"
        | "AppStoreConnect"
        | "Appdirect"
        | "Appfolio"
        | "Arxiv"
        | "Asaas"
        | "Astronomer"
        | "Athenahealth"
        | "Atlan"
        | "AutodeskConstructionCloud"
        | "Avalara"
        | "AwsAthena"
        | "AwsBatch"
        | "AwsBudgets"
        | "AwsCloudformation"
        | "AwsComputeOptimizer"
        | "AwsConfig"
        | "AwsConnect"
        | "AwsCostAndUsageReport"
        | "AwsCostAnomalyDetection"
        | "AwsCostExplorer"
        | "AwsGlueDataCatalog"
        | "AwsGuardduty"
        | "AwsHealth"
        | "AwsIamAccessAnalyzer"
        | "AwsInspector"
        | "AwsMacie"
        | "AwsOrganizations"
        | "AwsRdsPerformanceInsights"
        | "AwsSagemaker"
        | "AwsSavingsPlans"
        | "AwsSecurityHub"
        | "AwsSes"
        | "AwsStepFunctions"
        | "AwsSupport"
        | "AwsSystemsManager"
        | "AwsTrustedAdvisor"
        | "AwsWaf"
        | "AwsXray"
        | "AzureActivityLog"
        | "AzureAdvisor"
        | "AzureApiManagement"
        | "AzureApplicationInsights"
        | "AzureCostManagement"
        | "AzureDataExplorer"
        | "AzureDataFactory"
        | "AzureLogAnalytics"
        | "AzureMonitorAlerts"
        | "AzureMonitorMetrics"
        | "AzureOpenaiUsage"
        | "AzurePolicyInsights"
        | "AzureReservations"
        | "AzureResourceGraph"
        | "AzureResourceHealth"
        | "AzureServiceHealth"
        | "AzureSynapse"
        | "BackMarket"
        | "Beehiiv"
        | "Bigeye"
        | "BillCom"
        | "Billomat"
        | "BingWebmasterTools"
        | "Bitwarden"
        | "BlackbaudRaisersEdgeNxt"
        | "BlackboardLearn"
        | "Bling"
        | "Bloomerang"
        | "Bluesky"
        | "BolRetailer"
        | "Boulevard"
        | "Buffer"
        | "Bugherd"
        | "Buildium"
        | "Buttondown"
        | "BuyMeACoffee"
        | "Calendarific"
        | "Calibre"
        | "CanvasLms"
        | "Captivate"
        | "Cashfree"
        | "CastAi"
        | "Catchpoint"
        | "CdcOpenData"
        | "Census"
        | "Checkly"
        | "CircleSo"
        | "Classy"
        | "Cleartax"
        | "Clever"
        | "Clevertap"
        | "Cliniko"
        | "Clio"
        | "Clip"
        | "Cloudability"
        | "Cloudsmith"
        | "Cloudzero"
        | "Clover"
        | "Codemagic"
        | "Codescene"
        | "Collibra"
        | "Companycam"
        | "Conekta"
        | "ContaAzul"
        | "Contentsquare"
        | "Cortex"
        | "Courier"
        | "Crossref"
        | "CrowdstrikeFalcon"
        | "CubeCloud"
        | "D2lBrightspace"
        | "Dayforce"
        | "Debugbear"
        | "Descope"
        | "Develocity"
        | "Dialpad"
        | "Discord"
        | "Discourse"
        | "Donorbox"
        | "Doorloop"
        | "Dovetail"
        | "Drchrono"
        | "Dynamics365BusinessCentral"
        | "EcbDataPortal"
        | "Emarsys"
        | "Embrace"
        | "Entsoe"
        | "Eppo"
        | "Etsy"
        | "Eurostat"
        | "Faire"
        | "FarosAi"
        | "Fieldpulse"
        | "Fieldwire"
        | "Filevine"
        | "Finout"
        | "Five9"
        | "FlexeraCloudCost"
        | "Flutterwave"
        | "Fortnox"
        | "Fourthwall"
        | "Fred"
        | "Frontegg"
        | "FusionAuth"
        | "G2"
        | "Gcore"
        | "GcpApigee"
        | "GcpArtifactRegistry"
        | "GcpBigtable"
        | "GcpChronicle"
        | "GcpCloudAssetInventory"
        | "GcpCloudBilling"
        | "GcpCloudBuild"
        | "GcpCloudDeploy"
        | "GcpCloudDns"
        | "GcpCloudFunctions"
        | "GcpCloudLogging"
        | "GcpCloudMonitoring"
        | "GcpCloudRun"
        | "GcpCloudSpanner"
        | "GcpCloudSql"
        | "GcpCloudTrace"
        | "GcpCloudWorkflows"
        | "GcpComputeEngine"
        | "GcpContainerAnalysis"
        | "GcpDataflow"
        | "GcpDataplex"
        | "GcpDataproc"
        | "GcpErrorReporting"
        | "GcpGke"
        | "GcpPubsub"
        | "GcpRecaptchaEnterprise"
        | "GcpRecommender"
        | "GcpSecurityCommandCenter"
        | "Gdelt"
        | "GenesysCloud"
        | "Getdx"
        | "Ghost"
        | "Givebutter"
        | "Gleif"
        | "GooglePlayConsole"
        | "Guesty"
        | "Gumroad"
        | "HarnessCcm"
        | "HarnessSei"
        | "Harvest"
        | "Healthie"
        | "Hitpay"
        | "Hivebrite"
        | "Holded"
        | "Hostaway"
        | "HousecallPro"
        | "Humanitec"
        | "ImfData"
        | "Imperva"
        | "InfluxdbCloud"
        | "Iyzico"
        | "Jobtread"
        | "Kameleoon"
        | "KauflandMarketplace"
        | "Kestra"
        | "Kick"
        | "Kinde"
        | "Kion"
        | "Knowbe4"
        | "Komodor"
        | "Labelbox"
        | "Lawmatics"
        | "Learnworlds"
        | "LexwareOffice"
        | "Lightdash"
        | "Lodgify"
        | "Logicmonitor"
        | "Logrocket"
        | "LoopReturns"
        | "Mastodon"
        | "Meetup"
        | "Memberful"
        | "MercadoPago"
        | "Meteostat"
        | "Mews"
        | "Mezmo"
        | "Microsoft365UsageReports"
        | "MicrosoftAdvertising"
        | "MicrosoftClarity"
        | "MicrosoftDefenderCloudApps"
        | "MicrosoftDefenderEndpoint"
        | "MicrosoftDefenderForCloud"
        | "MicrosoftIntune"
        | "MicrosoftPurview"
        | "MicrosoftPurviewAudit"
        | "MicrosoftSentinel"
        | "MicrosoftTeamsCallRecords"
        | "Midtrans"
        | "MightyNetworks"
        | "Mindbody"
        | "Mirakl"
        | "Moesif"
        | "Moneybird"
        | "Moodle"
        | "Motherduck"
        | "Mycase"
        | "NagerDate"
        | "NeonCrm"
        | "Nexhealth"
        | "NoaaCdo"
        | "Nobl9"
        | "Nolt"
        | "Nops"
        | "NpmRegistry"
        | "Oecd"
        | "Okendo"
        | "Omni"
        | "Onelogin"
        | "OpenDental"
        | "OpenMeteo"
        | "Openalex"
        | "Opencorporates"
        | "Openfec"
        | "OpnPayments"
        | "Opslevel"
        | "OttoMarket"
        | "Ownerrez"
        | "Pagbank"
        | "Patreon"
        | "Pax8"
        | "Paychex"
        | "Paymob"
        | "Paymongo"
        | "Phonepe"
        | "Pike13"
        | "Pingone"
        | "PinterestOrganic"
        | "PlanningCenter"
        | "PluralsightFlow"
        | "Podbean"
        | "Postscript"
        | "PowerBiAdmin"
        | "Practicepanther"
        | "Preset"
        | "Procore"
        | "Productiv"
        | "ProofpointTap"
        | "Propertyware"
        | "Pubnub"
        | "Quay"
        | "Raken"
        | "RedpandaCloud"
        | "RentManager"
        | "Reverb"
        | "RocketMatter"
        | "Rubygems"
        | "Scalr"
        | "SecEdgar"
        | "SelectStar"
        | "SemanticScholar"
        | "Semrush"
        | "ServiceFusion"
        | "Servicem8"
        | "Servicetitan"
        | "Servicetrade"
        | "Sevdesk"
        | "Similarweb"
        | "Simpro"
        | "Sinch"
        | "Singlestore"
        | "Site24x7"
        | "Sleuth"
        | "Smartlook"
        | "Smartrecruiters"
        | "Smokeball"
        | "SodaCloud"
        | "Speedcurve"
        | "SpotIo"
        | "Sprig"
        | "Sprinklr"
        | "SproutSocial"
        | "StackOverflowForTeams"
        | "Stockx"
        | "TackleIo"
        | "Talkdesk"
        | "TeamupFitness"
        | "Tebra"
        | "Telnyx"
        | "Ternary"
        | "Thoughtspot"
        | "Thousandeyes"
        | "Threads"
        | "TiktokShop"
        | "TinyErp"
        | "Tinybird"
        | "Tipalti"
        | "Toast"
        | "Torii"
        | "Transistor"
        | "TrunkIo"
        | "Trustradius"
        | "Twitch"
        | "TwoC2p"
        | "UkCompaniesHouse"
        | "UkOns"
        | "UnComtrade"
        | "UsBea"
        | "UsBls"
        | "UsEia"
        | "UsTreasuryFiscalData"
        | "Vanta"
        | "Vendr"
        | "Virtuous"
        | "Vonage"
        | "WalmartMarketplace"
        | "Waydev"
        | "Wayfair"
        | "WhatsappBusinessManagement"
        | "WhoGho"
        | "Whop"
        | "Wiz"
        | "Wompi"
        | "Workiz"
        | "WorldBank"
        | "Xendit"
        | "Yoco"
        | "ZalandoZdirect"
        | "Zluri"
        | "Zylo"
        | "Tally"
        | "Nuntly"
        | "Vturb"
        | "Meltwater"
        | "UserCom"
        | "Latitude"
        | "Workato"
        | "SideShift"
        | "DuckLake"
        | "Starburst"
        | "Trino"
        | "Easybill"
        | "Bexio"
        | "Umami"
        | "Manychat"
        | "Kickstarter"
        | "Typesense"
        | "FirstPromoter"
        | "Zero"
        | "Inth"
        | "BCMS"
        | "Convonite"
        | "Hookdeck"
        | "Billit"
        | "Moxie"
        | "TripleWhale"
        | "Directus"
        | "Clay"
        | "TradableBits"
        | "Swan"
        | "Hyros"
        | "Odoo"
        | "Airbridge"
        | "Snovio"
        | "GoogleMerchantCenter"
        | "Raisely"
        | "RakutenAdvertising"
        | "Zitadel"
        | "DeelFlows"
        | "WindsorAi"
        | "Wix"
        | "Sevalla"
        | "Motion"
        | "ImpactPartner"
        | "Cloudinary"
        | "Uploadcare"
        | "WHMCS"
        | "MSG91"
        | "Depot"
        | "Schematic"
        | "Dokploy"
        | "Hootsuite"
        | "WisprFlow"
        | "SamCart"
        | "IronSourceAds"
        | "MicrosoftExcel"
        | "Profound"
        | "Airwallex"
        | "Polymarket"
        | "Kalshi"
        | "Capterra"
        | "GooglePostmasterTools"
        | "Growi"
        | "Clarify"
        | "DatoCMS"
        | "WPSOffice"
        | "TeraBox"
        | "SimonData"
        | "CommissionJunction"
        | "Liveblocks"
        | "NationBuilder"
        | "Tana"
        | "Zenchef"
        | "Lovable"
        | "Anvil"
        | "Coolify"
        | "SocialPilot"
        | "Strato"
        | "Medusa"
        | "Membrain"
        | "RecallAI";
    /**
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp
     */
    export type ExternalDataSourceCreateCreatedViaEnum = "web" | "api" | "mcp";
    export type ExternalDataSourceCreate = {
        /**
         * The source type (e.g. 'Postgres', 'Stripe').
         *
         * * `Ashby` - Ashby
         * * `Supabase` - Supabase
         * * `CustomerIO` - CustomerIO
         * * `Github` - Github
         * * `Stripe` - Stripe
         * * `Hubspot` - Hubspot
         * * `Postgres` - Postgres
         * * `Zendesk` - Zendesk
         * * `Snowflake` - Snowflake
         * * `Salesforce` - Salesforce
         * * `MySQL` - MySQL
         * * `MongoDB` - MongoDB
         * * `MSSQL` - MSSQL
         * * `Vitally` - Vitally
         * * `BigQuery` - BigQuery
         * * `Chargebee` - Chargebee
         * * `Clerk` - Clerk
         * * `GoogleAds` - GoogleAds
         * * `GoogleSearchConsole` - GoogleSearchConsole
         * * `TemporalIO` - TemporalIO
         * * `DoIt` - DoIt
         * * `GoogleSheets` - GoogleSheets
         * * `MetaAds` - MetaAds
         * * `Klaviyo` - Klaviyo
         * * `Mailchimp` - Mailchimp
         * * `Braze` - Braze
         * * `Mailjet` - Mailjet
         * * `Redshift` - Redshift
         * * `Polar` - Polar
         * * `RevenueCat` - RevenueCat
         * * `LinkedinAds` - LinkedinAds
         * * `RedditAds` - RedditAds
         * * `TikTokAds` - TikTokAds
         * * `BingAds` - BingAds
         * * `Shopify` - Shopify
         * * `Attio` - Attio
         * * `SnapchatAds` - SnapchatAds
         * * `Linear` - Linear
         * * `Intercom` - Intercom
         * * `Amplitude` - Amplitude
         * * `Mixpanel` - Mixpanel
         * * `Jira` - Jira
         * * `ActiveCampaign` - ActiveCampaign
         * * `Marketo` - Marketo
         * * `Adjust` - Adjust
         * * `AppsFlyer` - AppsFlyer
         * * `Freshdesk` - Freshdesk
         * * `GoogleAnalytics` - GoogleAnalytics
         * * `Pipedrive` - Pipedrive
         * * `SendGrid` - SendGrid
         * * `Slack` - Slack
         * * `PagerDuty` - PagerDuty
         * * `Asana` - Asana
         * * `Notion` - Notion
         * * `Airtable` - Airtable
         * * `Greenhouse` - Greenhouse
         * * `BambooHR` - BambooHR
         * * `Lever` - Lever
         * * `GitLab` - GitLab
         * * `Datadog` - Datadog
         * * `Sentry` - Sentry
         * * `Pendo` - Pendo
         * * `FullStory` - FullStory
         * * `AmazonAds` - AmazonAds
         * * `PinterestAds` - PinterestAds
         * * `AppleSearchAds` - AppleSearchAds
         * * `QuickBooks` - QuickBooks
         * * `Xero` - Xero
         * * `NetSuite` - NetSuite
         * * `WooCommerce` - WooCommerce
         * * `BigCommerce` - BigCommerce
         * * `PayPal` - PayPal
         * * `Square` - Square
         * * `Zoom` - Zoom
         * * `Trello` - Trello
         * * `Monday` - Monday
         * * `ClickUp` - ClickUp
         * * `Confluence` - Confluence
         * * `Recurly` - Recurly
         * * `SalesLoft` - SalesLoft
         * * `Outreach` - Outreach
         * * `Gong` - Gong
         * * `Calendly` - Calendly
         * * `Typeform` - Typeform
         * * `Iterable` - Iterable
         * * `ZohoCRM` - ZohoCRM
         * * `Close` - Close
         * * `Oracle` - Oracle
         * * `DynamoDB` - DynamoDB
         * * `Elasticsearch` - Elasticsearch
         * * `Kafka` - Kafka
         * * `LaunchDarkly` - LaunchDarkly
         * * `Braintree` - Braintree
         * * `Recharge` - Recharge
         * * `HelpScout` - HelpScout
         * * `Gorgias` - Gorgias
         * * `Instagram` - Instagram
         * * `YouTubeAnalytics` - YouTubeAnalytics
         * * `FacebookPages` - FacebookPages
         * * `TwitterAds` - TwitterAds
         * * `Workday` - Workday
         * * `ServiceNow` - ServiceNow
         * * `Pardot` - Pardot
         * * `Copper` - Copper
         * * `Front` - Front
         * * `ChartMogul` - ChartMogul
         * * `Zuora` - Zuora
         * * `Paddle` - Paddle
         * * `CircleCI` - CircleCI
         * * `CockroachDB` - CockroachDB
         * * `Firebase` - Firebase
         * * `AzureBlob` - AzureBlob
         * * `GoogleDrive` - GoogleDrive
         * * `OneDrive` - OneDrive
         * * `SharePoint` - SharePoint
         * * `Box` - Box
         * * `SFTP` - SFTP
         * * `MicrosoftTeams` - MicrosoftTeams
         * * `Aircall` - Aircall
         * * `Webflow` - Webflow
         * * `Okta` - Okta
         * * `Auth0` - Auth0
         * * `Productboard` - Productboard
         * * `Smartsheet` - Smartsheet
         * * `Wrike` - Wrike
         * * `Plaid` - Plaid
         * * `SurveyMonkey` - SurveyMonkey
         * * `Eventbrite` - Eventbrite
         * * `RingCentral` - RingCentral
         * * `Twilio` - Twilio
         * * `Freshsales` - Freshsales
         * * `Shortcut` - Shortcut
         * * `ConvertKit` - ConvertKit
         * * `Drip` - Drip
         * * `CampaignMonitor` - CampaignMonitor
         * * `MailerLite` - MailerLite
         * * `Omnisend` - Omnisend
         * * `Brevo` - Brevo
         * * `Postmark` - Postmark
         * * `Granola` - Granola
         * * `BuildBetter` - BuildBetter
         * * `Convex` - Convex
         * * `ClickHouse` - ClickHouse
         * * `Plain` - Plain
         * * `Resend` - Resend
         * * `PgAnalyze` - PgAnalyze
         * * `WorkOS` - WorkOS
         * * `AmazonS3` - AmazonS3
         * * `GoogleCloudStorage` - GoogleCloudStorage
         * * `Databricks` - Databricks
         * * `Dynamics365` - Dynamics365
         * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
         * * `Db2` - Db2
         * * `Heap` - Heap
         * * `AdobeAnalytics` - AdobeAnalytics
         * * `Matomo` - Matomo
         * * `Optimizely` - Optimizely
         * * `Adyen` - Adyen
         * * `GoCardless` - GoCardless
         * * `Mollie` - Mollie
         * * `CheckoutCom` - CheckoutCom
         * * `Branch` - Branch
         * * `Criteo` - Criteo
         * * `Outbrain` - Outbrain
         * * `Taboola` - Taboola
         * * `AdRoll` - AdRoll
         * * `DisplayVideo360` - DisplayVideo360
         * * `GoogleAdManager` - GoogleAdManager
         * * `CampaignManager360` - CampaignManager360
         * * `SearchAds360` - SearchAds360
         * * `AdobeCommerce` - AdobeCommerce
         * * `AmazonSellingPartner` - AmazonSellingPartner
         * * `Ebay` - Ebay
         * * `Commercetools` - Commercetools
         * * `LightspeedRetail` - LightspeedRetail
         * * `Shipmail` - Shipmail
         * * `ShipStation` - ShipStation
         * * `ConstantContact` - ConstantContact
         * * `Mailgun` - Mailgun
         * * `Eloqua` - Eloqua
         * * `Sailthru` - Sailthru
         * * `Ortto` - Ortto
         * * `Attentive` - Attentive
         * * `Kustomer` - Kustomer
         * * `Dixa` - Dixa
         * * `Gladly` - Gladly
         * * `Qualtrics` - Qualtrics
         * * `AzureDevOps` - AzureDevOps
         * * `RoktAds` - RoktAds
         * * `Rollbar` - Rollbar
         * * `Opsgenie` - Opsgenie
         * * `IncidentIo` - IncidentIo
         * * `Pingdom` - Pingdom
         * * `Cloudflare` - Cloudflare
         * * `CosmosDB` - CosmosDB
         * * `PlanetScaleMySQL` - PlanetScaleMySQL
         * * `PlanetScalePostgres` - PlanetScalePostgres
         * * `SapHana` - SapHana
         * * `Rippling` - Rippling
         * * `HiBob` - HiBob
         * * `Personio` - Personio
         * * `Deel` - Deel
         * * `AdpWorkforceNow` - AdpWorkforceNow
         * * `Paylocity` - Paylocity
         * * `Gusto` - Gusto
         * * `CultureAmp` - CultureAmp
         * * `Lattice` - Lattice
         * * `SageIntacct` - SageIntacct
         * * `FreshBooks` - FreshBooks
         * * `Expensify` - Expensify
         * * `Ramp` - Ramp
         * * `Brex` - Brex
         * * `Coupa` - Coupa
         * * `SapConcur` - SapConcur
         * * `Apollo` - Apollo
         * * `Crunchbase` - Crunchbase
         * * `ZoomInfo` - ZoomInfo
         * * `Clari` - Clari
         * * `Chorus` - Chorus
         * * `Coda` - Coda
         * * `Guru` - Guru
         * * `Dropbox` - Dropbox
         * * `Docusign` - Docusign
         * * `PandaDoc` - PandaDoc
         * * `SapErp` - SapErp
         * * `SapSuccessFactors` - SapSuccessFactors
         * * `OracleEbs` - OracleEbs
         * * `OracleFusion` - OracleFusion
         * * `AmazonSNS` - AmazonSNS
         * * `AmazonEventBridge` - AmazonEventBridge
         * * `AmazonSQS` - AmazonSQS
         * * `AmazonKinesis` - AmazonKinesis
         * * `AmazonCloudWatch` - AmazonCloudWatch
         * * `OpenAIAds` - OpenAIAds
         * * `OneHundredMs` - OneHundredMs
         * * `SevenShifts` - SevenShifts
         * * `AcuityScheduling` - AcuityScheduling
         * * `AgileCRM` - AgileCRM
         * * `Aha` - Aha
         * * `Airbyte` - Airbyte
         * * `Akeneo` - Akeneo
         * * `Algolia` - Algolia
         * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
         * * `ApifyDataset` - ApifyDataset
         * * `Appcues` - Appcues
         * * `Appfigures` - Appfigures
         * * `Appfollow` - Appfollow
         * * `Apptivo` - Apptivo
         * * `AssemblyAI` - AssemblyAI
         * * `Awin` - Awin
         * * `AwsCloudTrail` - AwsCloudTrail
         * * `AzureTableStorage` - AzureTableStorage
         * * `Babelforce` - Babelforce
         * * `Basecamp` - Basecamp
         * * `Beamer` - Beamer
         * * `BigMailer` - BigMailer
         * * `Bluetally` - Bluetally
         * * `BoldSign` - BoldSign
         * * `BreezyHR` - BreezyHR
         * * `Bugsnag` - Bugsnag
         * * `Buildkite` - Buildkite
         * * `Bunny` - Bunny
         * * `Buzzsprout` - Buzzsprout
         * * `CalCom` - CalCom
         * * `CallRail` - CallRail
         * * `Campayn` - Campayn
         * * `Canny` - Canny
         * * `CapsuleCRM` - CapsuleCRM
         * * `CaptainData` - CaptainData
         * * `CartCom` - CartCom
         * * `CastorEDC` - CastorEDC
         * * `Chameleon` - Chameleon
         * * `Chargedesk` - Chargedesk
         * * `Chargify` - Chargify
         * * `Chift` - Chift
         * * `Churnkey` - Churnkey
         * * `Cin7` - Cin7
         * * `CiscoMeraki` - CiscoMeraki
         * * `Clazar` - Clazar
         * * `Clockify` - Clockify
         * * `Clockodo` - Clockodo
         * * `Cloudbeds` - Cloudbeds
         * * `Coassemble` - Coassemble
         * * `Codefresh` - Codefresh
         * * `Concord` - Concord
         * * `ConfigCat` - ConfigCat
         * * `Couchbase` - Couchbase
         * * `Curve` - Curve
         * * `Customerly` - Customerly
         * * `Datascope` - Datascope
         * * `Dbt` - Dbt
         * * `Demodesk` - Demodesk
         * * `Deputy` - Deputy
         * * `DevinAI` - DevinAI
         * * `Docuseal` - Docuseal
         * * `Dolibarr` - Dolibarr
         * * `Dremio` - Dremio
         * * `DropboxSign` - DropboxSign
         * * `Dwolla` - Dwolla
         * * `EConomic` - EConomic
         * * `Easypost` - Easypost
         * * `Easypromos` - Easypromos
         * * `Elasticemail` - Elasticemail
         * * `EmailOctopus` - EmailOctopus
         * * `EmploymentHero` - EmploymentHero
         * * `Encharge` - Encharge
         * * `Eventee` - Eventee
         * * `Eventzilla` - Eventzilla
         * * `Everhour` - Everhour
         * * `EZOfficeInventory` - EZOfficeInventory
         * * `Factorial` - Factorial
         * * `Fastbill` - Fastbill
         * * `Fastly` - Fastly
         * * `Fauna` - Fauna
         * * `Feishu` - Feishu
         * * `Fillout` - Fillout
         * * `Finage` - Finage
         * * `Firebolt` - Firebolt
         * * `FireHydrant` - FireHydrant
         * * `Fleetio` - Fleetio
         * * `Flexmail` - Flexmail
         * * `Flexport` - Flexport
         * * `FloatApp` - FloatApp
         * * `Flowlu` - Flowlu
         * * `Formbricks` - Formbricks
         * * `Framer` - Framer
         * * `FreeAgent` - FreeAgent
         * * `Freightview` - Freightview
         * * `Freshcaller` - Freshcaller
         * * `Freshchat` - Freshchat
         * * `Freshservice` - Freshservice
         * * `Fulcrum` - Fulcrum
         * * `GainsightPx` - GainsightPx
         * * `GitBook` - GitBook
         * * `Glassfrog` - Glassfrog
         * * `Goldcast` - Goldcast
         * * `GoLogin` - GoLogin
         * * `Grafana` - Grafana
         * * `GreytHr` - GreytHr
         * * `Gridly` - Gridly
         * * `Harness` - Harness
         * * `Height` - Height
         * * `Hellobaton` - Hellobaton
         * * `HighLevel` - HighLevel
         * * `HoorayHR` - HoorayHR
         * * `Hubplanner` - Hubplanner
         * * `Humanitix` - Humanitix
         * * `Huntr` - Huntr
         * * `Inflowinventory` - Inflowinventory
         * * `InforNexus` - InforNexus
         * * `Insightful` - Insightful
         * * `Insightly` - Insightly
         * * `Instantly` - Instantly
         * * `Instatus` - Instatus
         * * `Intruder` - Intruder
         * * `Invoiced` - Invoiced
         * * `Invoiceninja` - Invoiceninja
         * * `JamfPro` - JamfPro
         * * `JobNimbus` - JobNimbus
         * * `Jotform` - Jotform
         * * `JudgeMeReviews` - JudgeMeReviews
         * * `JustCall` - JustCall
         * * `JustSift` - JustSift
         * * `K6Cloud` - K6Cloud
         * * `Katana` - Katana
         * * `Keka` - Keka
         * * `Kisi` - Kisi
         * * `Kissmetrics` - Kissmetrics
         * * `Klarna` - Klarna
         * * `Klaus` - Klaus
         * * `Lago` - Lago
         * * `Leadfeeder` - Leadfeeder
         * * `Lemlist` - Lemlist
         * * `LessAnnoyingCRM` - LessAnnoyingCRM
         * * `LinkedinPages` - LinkedinPages
         * * `Linkrunner` - Linkrunner
         * * `Linnworks` - Linnworks
         * * `Lob` - Lob
         * * `Lokalise` - Lokalise
         * * `Looker` - Looker
         * * `Luma` - Luma
         * * `MailerSend` - MailerSend
         * * `Mailosaur` - Mailosaur
         * * `Mailtrap` - Mailtrap
         * * `Mantle` - Mantle
         * * `Mention` - Mention
         * * `MercadoAds` - MercadoAds
         * * `Merge` - Merge
         * * `Metabase` - Metabase
         * * `Metricool` - Metricool
         * * `MicrosoftDataverse` - MicrosoftDataverse
         * * `MicrosoftEntraId` - MicrosoftEntraId
         * * `MicrosoftLists` - MicrosoftLists
         * * `Miro` - Miro
         * * `Missive` - Missive
         * * `MixMax` - MixMax
         * * `Mode` - Mode
         * * `Mux` - Mux
         * * `MyHours` - MyHours
         * * `N8n` - N8n
         * * `Navan` - Navan
         * * `NebiusAI` - NebiusAI
         * * `Nexiopay` - Nexiopay
         * * `NinjaOneRMM` - NinjaOneRMM
         * * `NoCRM` - NoCRM
         * * `NorthpassLMS` - NorthpassLMS
         * * `Nutshell` - Nutshell
         * * `Nylas` - Nylas
         * * `Oncehub` - Oncehub
         * * `Onepagecrm` - Onepagecrm
         * * `OneSignal` - OneSignal
         * * `Onfleet` - Onfleet
         * * `OpinionStage` - OpinionStage
         * * `OPUSWatch` - OPUSWatch
         * * `Orb` - Orb
         * * `Orbit` - Orbit
         * * `Oura` - Oura
         * * `Oveit` - Oveit
         * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
         * * `Paperform` - Paperform
         * * `Papersign` - Papersign
         * * `Partnerize` - Partnerize
         * * `PartnerStack` - PartnerStack
         * * `PayFit` - PayFit
         * * `Paystack` - Paystack
         * * `Pennylane` - Pennylane
         * * `Perk` - Perk
         * * `PersistIq` - PersistIq
         * * `Persona` - Persona
         * * `Phyllo` - Phyllo
         * * `Picqer` - Picqer
         * * `Pipeliner` - Pipeliner
         * * `PivotalTracker` - PivotalTracker
         * * `Piwik` - Piwik
         * * `Planhat` - Planhat
         * * `Plausible` - Plausible
         * * `Poplar` - Poplar
         * * `PrestaShop` - PrestaShop
         * * `Pretix` - Pretix
         * * `Primetric` - Primetric
         * * `Printavo` - Printavo
         * * `Printify` - Printify
         * * `Productive` - Productive
         * * `Pylon` - Pylon
         * * `Qonto` - Qonto
         * * `Qualaroo` - Qualaroo
         * * `Railz` - Railz
         * * `RDStationMarketing` - RDStationMarketing
         * * `Recruitee` - Recruitee
         * * `Reddit` - Reddit
         * * `ReferralHero` - ReferralHero
         * * `RentCast` - RentCast
         * * `Repairshopr` - Repairshopr
         * * `ReplyIo` - ReplyIo
         * * `RetailExpress` - RetailExpress
         * * `Retently` - Retently
         * * `RevolutMerchant` - RevolutMerchant
         * * `RocketChat` - RocketChat
         * * `Rocketlane` - Rocketlane
         * * `Rootly` - Rootly
         * * `Ruddr` - Ruddr
         * * `SafetyCulture` - SafetyCulture
         * * `SageHR` - SageHR
         * * `Salesflare` - Salesflare
         * * `SAPFieldglass` - SAPFieldglass
         * * `SavvyCal` - SavvyCal
         * * `Secoda` - Secoda
         * * `Segment` - Segment
         * * `Sendowl` - Sendowl
         * * `SendPulse` - SendPulse
         * * `Senseforce` - Senseforce
         * * `Serpstat` - Serpstat
         * * `Sharetribe` - Sharetribe
         * * `Shippo` - Shippo
         * * `ShopWired` - ShopWired
         * * `Shortio` - Shortio
         * * `Shutterstock` - Shutterstock
         * * `SigmaComputing` - SigmaComputing
         * * `SignNow` - SignNow
         * * `SimpleCast` - SimpleCast
         * * `Simplesat` - Simplesat
         * * `Smaily` - Smaily
         * * `SmartEngage` - SmartEngage
         * * `Smartreach` - Smartreach
         * * `Smartwaiver` - Smartwaiver
         * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
         * * `SonarCloud` - SonarCloud
         * * `SparkPost` - SparkPost
         * * `SplitIo` - SplitIo
         * * `SpotifyAds` - SpotifyAds
         * * `SpotlerCRM` - SpotlerCRM
         * * `Squarespace` - Squarespace
         * * `Statsig` - Statsig
         * * `Statuspage` - Statuspage
         * * `Stigg` - Stigg
         * * `Strava` - Strava
         * * `SurveySparrow` - SurveySparrow
         * * `Survicate` - Survicate
         * * `Svix` - Svix
         * * `Systeme` - Systeme
         * * `Tavus` - Tavus
         * * `Teamtailor` - Teamtailor
         * * `Teamwork` - Teamwork
         * * `Tempo` - Tempo
         * * `Testrail` - Testrail
         * * `Thinkific` - Thinkific
         * * `ThinkificCourses` - ThinkificCourses
         * * `ThriveLearning` - ThriveLearning
         * * `Ticketmaster` - Ticketmaster
         * * `TicketTailor` - TicketTailor
         * * `TickTick` - TickTick
         * * `Timely` - Timely
         * * `Tinyemail` - Tinyemail
         * * `Todoist` - Todoist
         * * `Toggl` - Toggl
         * * `TrackPMS` - TrackPMS
         * * `Tremendous` - Tremendous
         * * `TrustPilot` - TrustPilot
         * * `Twitter` - Twitter
         * * `TyntecSMS` - TyntecSMS
         * * `Unleash` - Unleash
         * * `UpPromote` - UpPromote
         * * `Uptick` - Uptick
         * * `Uservoice` - Uservoice
         * * `Vantage` - Vantage
         * * `Veeqo` - Veeqo
         * * `Vercel` - Vercel
         * * `VismaEconomic` - VismaEconomic
         * * `VWO` - VWO
         * * `Waiteraid` - Waiteraid
         * * `Wasabi` - Wasabi
         * * `WhenIWork` - WhenIWork
         * * `Wordpress` - Wordpress
         * * `Workable` - Workable
         * * `Workflowmax` - Workflowmax
         * * `Workramp` - Workramp
         * * `Wufoo` - Wufoo
         * * `Xsolla` - Xsolla
         * * `YandexMetrica` - YandexMetrica
         * * `Yotpo` - Yotpo
         * * `Ynab` - Ynab
         * * `Younium` - Younium
         * * `YouSign` - YouSign
         * * `YoutubeData` - YoutubeData
         * * `ZapierSupportedStorage` - ZapierSupportedStorage
         * * `ZapSign` - ZapSign
         * * `ZendeskSell` - ZendeskSell
         * * `ZendeskSunshine` - ZendeskSunshine
         * * `Zenefits` - Zenefits
         * * `Zenloop` - Zenloop
         * * `ZohoAnalytics` - ZohoAnalytics
         * * `ZohoBigin` - ZohoBigin
         * * `ZohoBilling` - ZohoBilling
         * * `ZohoBooks` - ZohoBooks
         * * `ZohoCampaign` - ZohoCampaign
         * * `ZohoDesk` - ZohoDesk
         * * `ZohoExpense` - ZohoExpense
         * * `ZohoInventory` - ZohoInventory
         * * `ZohoInvoice` - ZohoInvoice
         * * `ZonkaFeedback` - ZonkaFeedback
         * * `AlphaVantage` - AlphaVantage
         * * `Aviationstack` - Aviationstack
         * * `Bitly` - Bitly
         * * `Blogger` - Blogger
         * * `Breezometer` - Breezometer
         * * `CareQualityCommission` - CareQualityCommission
         * * `Cimis` - Cimis
         * * `CoinApi` - CoinApi
         * * `CoinGecko` - CoinGecko
         * * `CoinMarketCap` - CoinMarketCap
         * * `DingConnect` - DingConnect
         * * `Dockerhub` - Dockerhub
         * * `ExchangeRatesApi` - ExchangeRatesApi
         * * `FinancialModelling` - FinancialModelling
         * * `Finnhub` - Finnhub
         * * `Finnworlds` - Finnworlds
         * * `Giphy` - Giphy
         * * `Gmail` - Gmail
         * * `GNews` - GNews
         * * `GoogleCalendar` - GoogleCalendar
         * * `GoogleClassroom` - GoogleClassroom
         * * `GoogleDirectory` - GoogleDirectory
         * * `GoogleForms` - GoogleForms
         * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
         * * `GoogleTasks` - GoogleTasks
         * * `GoogleWebfonts` - GoogleWebfonts
         * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
         * * `HuggingFace` - HuggingFace
         * * `IlluminaBasespace` - IlluminaBasespace
         * * `Imagga` - Imagga
         * * `Interzoid` - Interzoid
         * * `IP2Whois` - IP2Whois
         * * `KYVE` - KYVE
         * * `Marketstack` - Marketstack
         * * `Mendeley` - Mendeley
         * * `Nasa` - Nasa
         * * `NewYorkTimes` - NewYorkTimes
         * * `NewsApi` - NewsApi
         * * `NewsData` - NewsData
         * * `OpenDataDc` - OpenDataDc
         * * `OpenExchangeRates` - OpenExchangeRates
         * * `OpenAQ` - OpenAQ
         * * `OpenFDA` - OpenFDA
         * * `OpenWeather` - OpenWeather
         * * `Outlook` - Outlook
         * * `Perigon` - Perigon
         * * `Pexels` - Pexels
         * * `Pocket` - Pocket
         * * `Polygon` - Polygon
         * * `PyPI` - PyPI
         * * `Recreation` - Recreation
         * * `RKICovid` - RKICovid
         * * `Rss` - Rss
         * * `SimFin` - SimFin
         * * `StockData` - StockData
         * * `Guardian` - Guardian
         * * `TMDb` - TMDb
         * * `TVMaze` - TVMaze
         * * `TwelveData` - TwelveData
         * * `Ubidots` - Ubidots
         * * `USCensus` - USCensus
         * * `Watchmode` - Watchmode
         * * `WikipediaPageviews` - WikipediaPageviews
         * * `YahooFinance` - YahooFinance
         * * `Clarifai` - Clarifai
         * * `Adapty` - Adapty
         * * `Braintrust` - Braintrust
         * * `StreamElements` - StreamElements
         * * `Streamlabs` - Streamlabs
         * * `Datorama` - Datorama
         * * `Ahrefs` - Ahrefs
         * * `Lightfield` - Lightfield
         * * `Appstack` - Appstack
         * * `Razorpay` - Razorpay
         * * `Neon` - Neon
         * * `NewRelic` - NewRelic
         * * `Custom` - Custom
         * * `Tile38` - Tile38
         * * `Chatwoot` - Chatwoot
         * * `Sanity` - Sanity
         * * `Metronome` - Metronome
         * * `Jobber` - Jobber
         * * `Knock` - Knock
         * * `Leexi` - Leexi
         * * `RB2B` - RB2B
         * * `Superwall` - Superwall
         * * `Liana` - Liana
         * * `TawkTo` - TawkTo
         * * `Hightouch` - Hightouch
         * * `LemonSqueezy` - LemonSqueezy
         * * `Ikas` - Ikas
         * * `Talkwalker` - Talkwalker
         * * `NextdoorAds` - NextdoorAds
         * * `AppLovin` - AppLovin
         * * `Baserow` - Baserow
         * * `Plunk` - Plunk
         * * `Dub` - Dub
         * * `AirOps` - AirOps
         * * `Podium` - Podium
         * * `Loops` - Loops
         * * `Redis` - Redis
         * * `Mercury` - Mercury
         * * `Gojiberry` - Gojiberry
         * * `Teachable` - Teachable
         * * `PeecAI` - PeecAI
         * * `Healthchecks` - Healthchecks
         * * `Impact` - Impact
         * * `AikidoSecurity` - AikidoSecurity
         * * `Alguna` - Alguna
         * * `Anthropic` - Anthropic
         * * `Appwrite` - Appwrite
         * * `BlandAI` - BlandAI
         * * `BrowseAI` - BrowseAI
         * * `BrowserUse` - BrowserUse
         * * `ChartHop` - ChartHop
         * * `Cody` - Cody
         * * `Cursor` - Cursor
         * * `Decagon` - Decagon
         * * `Deepgram` - Deepgram
         * * `ElevenLabs` - ElevenLabs
         * * `Harvey` - Harvey
         * * `Hyperspell` - Hyperspell
         * * `Langfuse` - Langfuse
         * * `LingoDev` - LingoDev
         * * `M3ter` - M3ter
         * * `Maxio` - Maxio
         * * `Metorial` - Metorial
         * * `OpenRouter` - OpenRouter
         * * `TogetherAI` - TogetherAI
         * * `Vapi` - Vapi
         * * `Vespa` - Vespa
         * * `Writesonic` - Writesonic
         * * `Aiven` - Aiven
         * * `Aviator` - Aviator
         * * `Backblaze` - Backblaze
         * * `Baseten` - Baseten
         * * `Browserbase` - Browserbase
         * * `Cohere` - Cohere
         * * `DenoDeploy` - DenoDeploy
         * * `DigitalOcean` - DigitalOcean
         * * `E2B` - E2B
         * * `Fintoc` - Fintoc
         * * `Firecrawl` - Firecrawl
         * * `FireworksAI` - FireworksAI
         * * `FlyIo` - FlyIo
         * * `Groq` - Groq
         * * `GrowthBook` - GrowthBook
         * * `Gumloop` - Gumloop
         * * `Hatchet` - Hatchet
         * * `Helicone` - Helicone
         * * `Heroku` - Heroku
         * * `Hetzner` - Hetzner
         * * `HeyGen` - HeyGen
         * * `Infisical` - Infisical
         * * `Inngest` - Inngest
         * * `KapaAI` - KapaAI
         * * `Kernel` - Kernel
         * * `Koyeb` - Koyeb
         * * `LambdaLabs` - LambdaLabs
         * * `LangSmith` - LangSmith
         * * `Linode` - Linode
         * * `LlamaCloud` - LlamaCloud
         * * `Mem0` - Mem0
         * * `Metriport` - Metriport
         * * `Mintlify` - Mintlify
         * * `MistralAI` - MistralAI
         * * `Mono` - Mono
         * * `Netlify` - Netlify
         * * `Northflank` - Northflank
         * * `OpenAI` - OpenAI
         * * `Pinecone` - Pinecone
         * * `PlatformSh` - PlatformSh
         * * `PromptingCompany` - PromptingCompany
         * * `Qdrant` - Qdrant
         * * `Render` - Render
         * * `Replicate` - Replicate
         * * `RetellAI` - RetellAI
         * * `Roark` - Roark
         * * `RunPod` - RunPod
         * * `ScaleAI` - ScaleAI
         * * `Scaleway` - Scaleway
         * * `SigNoz` - SigNoz
         * * `Sim` - Sim
         * * `Skyvern` - Skyvern
         * * `Slash` - Slash
         * * `Synthesia` - Synthesia
         * * `Telli` - Telli
         * * `TerraApi` - TerraApi
         * * `TriggerDev` - TriggerDev
         * * `Turso` - Turso
         * * `Singular` - Singular
         * * `Swonkie` - Swonkie
         * * `TwelveLabs` - TwelveLabs
         * * `Twenty` - Twenty
         * * `Unstructured` - Unstructured
         * * `Upstash` - Upstash
         * * `Vellum` - Vellum
         * * `Vultr` - Vultr
         * * `Windmill` - Windmill
         * * `Zep` - Zep
         * * `Hex` - Hex
         * * `Sumsub` - Sumsub
         * * `GoogleChat` - GoogleChat
         * * `Kickscale` - Kickscale
         * * `Zellify` - Zellify
         * * `RudderStack` - RudderStack
         * * `DodoPayments` - DodoPayments
         * * `Salestrics` - Salestrics
         * * `Doppler` - Doppler
         * * `Usersnap` - Usersnap
         * * `Asknicely` - Asknicely
         * * `Featurebase` - Featurebase
         * * `Frill` - Frill
         * * `Bettermode` - Bettermode
         * * `Dynatrace` - Dynatrace
         * * `Honeycomb` - Honeycomb
         * * `SumoLogic` - SumoLogic
         * * `LogzIO` - LogzIO
         * * `Coralogix` - Coralogix
         * * `BetterStack` - BetterStack
         * * `Raygun` - Raygun
         * * `Honeybadger` - Honeybadger
         * * `Airbrake` - Airbrake
         * * `Appsignal` - Appsignal
         * * `Appdynamics` - Appdynamics
         * * `Instana` - Instana
         * * `SplunkObservabilityCloud` - SplunkObservabilityCloud
         * * `Uptimerobot` - Uptimerobot
         * * `Statuscake` - Statuscake
         * * `Tailscale` - Tailscale
         * * `Flagsmith` - Flagsmith
         * * `Xmatters` - Xmatters
         * * `Squadcast` - Squadcast
         * * `Zenduty` - Zenduty
         * * `Cronitor` - Cronitor
         * * `Jenkins` - Jenkins
         * * `Bitbucket` - Bitbucket
         * * `Gitea` - Gitea
         * * `Teamcity` - Teamcity
         * * `TravisCI` - TravisCI
         * * `Semaphore` - Semaphore
         * * `CircleciInsights` - CircleciInsights
         * * `OctopusDeploy` - OctopusDeploy
         * * `Sourcegraph` - Sourcegraph
         * * `Bitrise` - Bitrise
         * * `Gerrit` - Gerrit
         * * `TerraformCloud` - TerraformCloud
         * * `PulumiCloud` - PulumiCloud
         * * `Spacelift` - Spacelift
         * * `Railway` - Railway
         * * `Argocd` - Argocd
         * * `PrefectCloud` - PrefectCloud
         * * `DagsterCloud` - DagsterCloud
         * * `Env0` - Env0
         * * `Kubecost` - Kubecost
         * * `Snyk` - Snyk
         * * `Semgrep` - Semgrep
         * * `Veracode` - Veracode
         * * `Checkmarx` - Checkmarx
         * * `Gitguardian` - Gitguardian
         * * `QualysVmdr` - QualysVmdr
         * * `Rapid7Insightvm` - Rapid7Insightvm
         * * `TenableVulnerabilityManagement` - TenableVulnerabilityManagement
         * * `Sentinelone` - Sentinelone
         * * `Lacework` - Lacework
         * * `OrcaSecurity` - OrcaSecurity
         * * `Drata` - Drata
         * * `Secureframe` - Secureframe
         * * `CiscoDuo` - CiscoDuo
         * * `Jumpcloud` - Jumpcloud
         * * `OnePassword` - OnePassword
         * * `Stytch` - Stytch
         * * `Sonarqube` - Sonarqube
         * * `Codecov` - Codecov
         * * `Coveralls` - Coveralls
         * * `Codacy` - Codacy
         * * `Deepsource` - Deepsource
         * * `Linearb` - Linearb
         * * `Jellyfish` - Jellyfish
         * * `Swarmia` - Swarmia
         * * `Packagist` - Packagist
         * * `Nuget` - Nuget
         * * `CratesIO` - CratesIO
         * * `SonatypeNexus` - SonatypeNexus
         * * `JfrogArtifactory` - JfrogArtifactory
         * * `Snowplow` - Snowplow
         * * `WeightsAndBiases` - WeightsAndBiases
         * * `MonteCarlo` - MonteCarlo
         * * `Metaplane` - Metaplane
         * * `Datahub` - Datahub
         * * `ClickhouseCloud` - ClickhouseCloud
         * * `ConfluentCloud` - ConfluentCloud
         * * `KongKonnect` - KongKonnect
         * * `Kandji` - Kandji
         * * `Automox` - Automox
         * * `Autumn` - Autumn
         * * `GetStream` - GetStream
         * * `Octolens` - Octolens
         * * `Kajabi` - Kajabi
         * * `Shopware` - Shopware
         * * `Dubsado` - Dubsado
         * * `Campfire` - Campfire
         * * `PromptWatch` - PromptWatch
         * * `Crisp` - Crisp
         * * `Kommo` - Kommo
         * * `Axiom` - Axiom
         * * `Plivo` - Plivo
         * * `DataForSEO` - DataForSEO
         * * `Sleekplan` - Sleekplan
         * * `AbTasty` - AbTasty
         * * `Ably` - Ably
         * * `AbnormalSecurity` - AbnormalSecurity
         * * `Acast` - Acast
         * * `Acculynx` - Acculynx
         * * `Actionstep` - Actionstep
         * * `Aftership` - Aftership
         * * `AhaIdeas` - AhaIdeas
         * * `AkamaiReporting` - AkamaiReporting
         * * `Alation` - Alation
         * * `Alegra` - Alegra
         * * `Allegro` - Allegro
         * * `AnodotCost` - AnodotCost
         * * `Anomalo` - Anomalo
         * * `Apaleo` - Apaleo
         * * `Apitally` - Apitally
         * * `AppStoreConnect` - AppStoreConnect
         * * `Appdirect` - Appdirect
         * * `Appfolio` - Appfolio
         * * `Arxiv` - Arxiv
         * * `Asaas` - Asaas
         * * `Astronomer` - Astronomer
         * * `Athenahealth` - Athenahealth
         * * `Atlan` - Atlan
         * * `AutodeskConstructionCloud` - AutodeskConstructionCloud
         * * `Avalara` - Avalara
         * * `AwsAthena` - AwsAthena
         * * `AwsBatch` - AwsBatch
         * * `AwsBudgets` - AwsBudgets
         * * `AwsCloudformation` - AwsCloudformation
         * * `AwsComputeOptimizer` - AwsComputeOptimizer
         * * `AwsConfig` - AwsConfig
         * * `AwsConnect` - AwsConnect
         * * `AwsCostAndUsageReport` - AwsCostAndUsageReport
         * * `AwsCostAnomalyDetection` - AwsCostAnomalyDetection
         * * `AwsCostExplorer` - AwsCostExplorer
         * * `AwsGlueDataCatalog` - AwsGlueDataCatalog
         * * `AwsGuardduty` - AwsGuardduty
         * * `AwsHealth` - AwsHealth
         * * `AwsIamAccessAnalyzer` - AwsIamAccessAnalyzer
         * * `AwsInspector` - AwsInspector
         * * `AwsMacie` - AwsMacie
         * * `AwsOrganizations` - AwsOrganizations
         * * `AwsRdsPerformanceInsights` - AwsRdsPerformanceInsights
         * * `AwsSagemaker` - AwsSagemaker
         * * `AwsSavingsPlans` - AwsSavingsPlans
         * * `AwsSecurityHub` - AwsSecurityHub
         * * `AwsSes` - AwsSes
         * * `AwsStepFunctions` - AwsStepFunctions
         * * `AwsSupport` - AwsSupport
         * * `AwsSystemsManager` - AwsSystemsManager
         * * `AwsTrustedAdvisor` - AwsTrustedAdvisor
         * * `AwsWaf` - AwsWaf
         * * `AwsXray` - AwsXray
         * * `AzureActivityLog` - AzureActivityLog
         * * `AzureAdvisor` - AzureAdvisor
         * * `AzureApiManagement` - AzureApiManagement
         * * `AzureApplicationInsights` - AzureApplicationInsights
         * * `AzureCostManagement` - AzureCostManagement
         * * `AzureDataExplorer` - AzureDataExplorer
         * * `AzureDataFactory` - AzureDataFactory
         * * `AzureLogAnalytics` - AzureLogAnalytics
         * * `AzureMonitorAlerts` - AzureMonitorAlerts
         * * `AzureMonitorMetrics` - AzureMonitorMetrics
         * * `AzureOpenaiUsage` - AzureOpenaiUsage
         * * `AzurePolicyInsights` - AzurePolicyInsights
         * * `AzureReservations` - AzureReservations
         * * `AzureResourceGraph` - AzureResourceGraph
         * * `AzureResourceHealth` - AzureResourceHealth
         * * `AzureServiceHealth` - AzureServiceHealth
         * * `AzureSynapse` - AzureSynapse
         * * `BackMarket` - BackMarket
         * * `Beehiiv` - Beehiiv
         * * `Bigeye` - Bigeye
         * * `BillCom` - BillCom
         * * `Billomat` - Billomat
         * * `BingWebmasterTools` - BingWebmasterTools
         * * `Bitwarden` - Bitwarden
         * * `BlackbaudRaisersEdgeNxt` - BlackbaudRaisersEdgeNxt
         * * `BlackboardLearn` - BlackboardLearn
         * * `Bling` - Bling
         * * `Bloomerang` - Bloomerang
         * * `Bluesky` - Bluesky
         * * `BolRetailer` - BolRetailer
         * * `Boulevard` - Boulevard
         * * `Buffer` - Buffer
         * * `Bugherd` - Bugherd
         * * `Buildium` - Buildium
         * * `Buttondown` - Buttondown
         * * `BuyMeACoffee` - BuyMeACoffee
         * * `Calendarific` - Calendarific
         * * `Calibre` - Calibre
         * * `CanvasLms` - CanvasLms
         * * `Captivate` - Captivate
         * * `Cashfree` - Cashfree
         * * `CastAi` - CastAi
         * * `Catchpoint` - Catchpoint
         * * `CdcOpenData` - CdcOpenData
         * * `Census` - Census
         * * `Checkly` - Checkly
         * * `CircleSo` - CircleSo
         * * `Classy` - Classy
         * * `Cleartax` - Cleartax
         * * `Clever` - Clever
         * * `Clevertap` - Clevertap
         * * `Cliniko` - Cliniko
         * * `Clio` - Clio
         * * `Clip` - Clip
         * * `Cloudability` - Cloudability
         * * `Cloudsmith` - Cloudsmith
         * * `Cloudzero` - Cloudzero
         * * `Clover` - Clover
         * * `Codemagic` - Codemagic
         * * `Codescene` - Codescene
         * * `Collibra` - Collibra
         * * `Companycam` - Companycam
         * * `Conekta` - Conekta
         * * `ContaAzul` - ContaAzul
         * * `Contentsquare` - Contentsquare
         * * `Cortex` - Cortex
         * * `Courier` - Courier
         * * `Crossref` - Crossref
         * * `CrowdstrikeFalcon` - CrowdstrikeFalcon
         * * `CubeCloud` - CubeCloud
         * * `D2lBrightspace` - D2lBrightspace
         * * `Dayforce` - Dayforce
         * * `Debugbear` - Debugbear
         * * `Descope` - Descope
         * * `Develocity` - Develocity
         * * `Dialpad` - Dialpad
         * * `Discord` - Discord
         * * `Discourse` - Discourse
         * * `Donorbox` - Donorbox
         * * `Doorloop` - Doorloop
         * * `Dovetail` - Dovetail
         * * `Drchrono` - Drchrono
         * * `Dynamics365BusinessCentral` - Dynamics365BusinessCentral
         * * `EcbDataPortal` - EcbDataPortal
         * * `Emarsys` - Emarsys
         * * `Embrace` - Embrace
         * * `Entsoe` - Entsoe
         * * `Eppo` - Eppo
         * * `Etsy` - Etsy
         * * `Eurostat` - Eurostat
         * * `Faire` - Faire
         * * `FarosAi` - FarosAi
         * * `Fieldpulse` - Fieldpulse
         * * `Fieldwire` - Fieldwire
         * * `Filevine` - Filevine
         * * `Finout` - Finout
         * * `Five9` - Five9
         * * `FlexeraCloudCost` - FlexeraCloudCost
         * * `Flutterwave` - Flutterwave
         * * `Fortnox` - Fortnox
         * * `Fourthwall` - Fourthwall
         * * `Fred` - Fred
         * * `Frontegg` - Frontegg
         * * `FusionAuth` - FusionAuth
         * * `G2` - G2
         * * `Gcore` - Gcore
         * * `GcpApigee` - GcpApigee
         * * `GcpArtifactRegistry` - GcpArtifactRegistry
         * * `GcpBigtable` - GcpBigtable
         * * `GcpChronicle` - GcpChronicle
         * * `GcpCloudAssetInventory` - GcpCloudAssetInventory
         * * `GcpCloudBilling` - GcpCloudBilling
         * * `GcpCloudBuild` - GcpCloudBuild
         * * `GcpCloudDeploy` - GcpCloudDeploy
         * * `GcpCloudDns` - GcpCloudDns
         * * `GcpCloudFunctions` - GcpCloudFunctions
         * * `GcpCloudLogging` - GcpCloudLogging
         * * `GcpCloudMonitoring` - GcpCloudMonitoring
         * * `GcpCloudRun` - GcpCloudRun
         * * `GcpCloudSpanner` - GcpCloudSpanner
         * * `GcpCloudSql` - GcpCloudSql
         * * `GcpCloudTrace` - GcpCloudTrace
         * * `GcpCloudWorkflows` - GcpCloudWorkflows
         * * `GcpComputeEngine` - GcpComputeEngine
         * * `GcpContainerAnalysis` - GcpContainerAnalysis
         * * `GcpDataflow` - GcpDataflow
         * * `GcpDataplex` - GcpDataplex
         * * `GcpDataproc` - GcpDataproc
         * * `GcpErrorReporting` - GcpErrorReporting
         * * `GcpGke` - GcpGke
         * * `GcpPubsub` - GcpPubsub
         * * `GcpRecaptchaEnterprise` - GcpRecaptchaEnterprise
         * * `GcpRecommender` - GcpRecommender
         * * `GcpSecurityCommandCenter` - GcpSecurityCommandCenter
         * * `Gdelt` - Gdelt
         * * `GenesysCloud` - GenesysCloud
         * * `Getdx` - Getdx
         * * `Ghost` - Ghost
         * * `Givebutter` - Givebutter
         * * `Gleif` - Gleif
         * * `GooglePlayConsole` - GooglePlayConsole
         * * `Guesty` - Guesty
         * * `Gumroad` - Gumroad
         * * `HarnessCcm` - HarnessCcm
         * * `HarnessSei` - HarnessSei
         * * `Harvest` - Harvest
         * * `Healthie` - Healthie
         * * `Hitpay` - Hitpay
         * * `Hivebrite` - Hivebrite
         * * `Holded` - Holded
         * * `Hostaway` - Hostaway
         * * `HousecallPro` - HousecallPro
         * * `Humanitec` - Humanitec
         * * `ImfData` - ImfData
         * * `Imperva` - Imperva
         * * `InfluxdbCloud` - InfluxdbCloud
         * * `Iyzico` - Iyzico
         * * `Jobtread` - Jobtread
         * * `Kameleoon` - Kameleoon
         * * `KauflandMarketplace` - KauflandMarketplace
         * * `Kestra` - Kestra
         * * `Kick` - Kick
         * * `Kinde` - Kinde
         * * `Kion` - Kion
         * * `Knowbe4` - Knowbe4
         * * `Komodor` - Komodor
         * * `Labelbox` - Labelbox
         * * `Lawmatics` - Lawmatics
         * * `Learnworlds` - Learnworlds
         * * `LexwareOffice` - LexwareOffice
         * * `Lightdash` - Lightdash
         * * `Lodgify` - Lodgify
         * * `Logicmonitor` - Logicmonitor
         * * `Logrocket` - Logrocket
         * * `LoopReturns` - LoopReturns
         * * `Mastodon` - Mastodon
         * * `Meetup` - Meetup
         * * `Memberful` - Memberful
         * * `MercadoPago` - MercadoPago
         * * `Meteostat` - Meteostat
         * * `Mews` - Mews
         * * `Mezmo` - Mezmo
         * * `Microsoft365UsageReports` - Microsoft365UsageReports
         * * `MicrosoftAdvertising` - MicrosoftAdvertising
         * * `MicrosoftClarity` - MicrosoftClarity
         * * `MicrosoftDefenderCloudApps` - MicrosoftDefenderCloudApps
         * * `MicrosoftDefenderEndpoint` - MicrosoftDefenderEndpoint
         * * `MicrosoftDefenderForCloud` - MicrosoftDefenderForCloud
         * * `MicrosoftIntune` - MicrosoftIntune
         * * `MicrosoftPurview` - MicrosoftPurview
         * * `MicrosoftPurviewAudit` - MicrosoftPurviewAudit
         * * `MicrosoftSentinel` - MicrosoftSentinel
         * * `MicrosoftTeamsCallRecords` - MicrosoftTeamsCallRecords
         * * `Midtrans` - Midtrans
         * * `MightyNetworks` - MightyNetworks
         * * `Mindbody` - Mindbody
         * * `Mirakl` - Mirakl
         * * `Moesif` - Moesif
         * * `Moneybird` - Moneybird
         * * `Moodle` - Moodle
         * * `Motherduck` - Motherduck
         * * `Mycase` - Mycase
         * * `NagerDate` - NagerDate
         * * `NeonCrm` - NeonCrm
         * * `Nexhealth` - Nexhealth
         * * `NoaaCdo` - NoaaCdo
         * * `Nobl9` - Nobl9
         * * `Nolt` - Nolt
         * * `Nops` - Nops
         * * `NpmRegistry` - NpmRegistry
         * * `Oecd` - Oecd
         * * `Okendo` - Okendo
         * * `Omni` - Omni
         * * `Onelogin` - Onelogin
         * * `OpenDental` - OpenDental
         * * `OpenMeteo` - OpenMeteo
         * * `Openalex` - Openalex
         * * `Opencorporates` - Opencorporates
         * * `Openfec` - Openfec
         * * `OpnPayments` - OpnPayments
         * * `Opslevel` - Opslevel
         * * `OttoMarket` - OttoMarket
         * * `Ownerrez` - Ownerrez
         * * `Pagbank` - Pagbank
         * * `Patreon` - Patreon
         * * `Pax8` - Pax8
         * * `Paychex` - Paychex
         * * `Paymob` - Paymob
         * * `Paymongo` - Paymongo
         * * `Phonepe` - Phonepe
         * * `Pike13` - Pike13
         * * `Pingone` - Pingone
         * * `PinterestOrganic` - PinterestOrganic
         * * `PlanningCenter` - PlanningCenter
         * * `PluralsightFlow` - PluralsightFlow
         * * `Podbean` - Podbean
         * * `Postscript` - Postscript
         * * `PowerBiAdmin` - PowerBiAdmin
         * * `Practicepanther` - Practicepanther
         * * `Preset` - Preset
         * * `Procore` - Procore
         * * `Productiv` - Productiv
         * * `ProofpointTap` - ProofpointTap
         * * `Propertyware` - Propertyware
         * * `Pubnub` - Pubnub
         * * `Quay` - Quay
         * * `Raken` - Raken
         * * `RedpandaCloud` - RedpandaCloud
         * * `RentManager` - RentManager
         * * `Reverb` - Reverb
         * * `RocketMatter` - RocketMatter
         * * `Rubygems` - Rubygems
         * * `Scalr` - Scalr
         * * `SecEdgar` - SecEdgar
         * * `SelectStar` - SelectStar
         * * `SemanticScholar` - SemanticScholar
         * * `Semrush` - Semrush
         * * `ServiceFusion` - ServiceFusion
         * * `Servicem8` - Servicem8
         * * `Servicetitan` - Servicetitan
         * * `Servicetrade` - Servicetrade
         * * `Sevdesk` - Sevdesk
         * * `Similarweb` - Similarweb
         * * `Simpro` - Simpro
         * * `Sinch` - Sinch
         * * `Singlestore` - Singlestore
         * * `Site24x7` - Site24x7
         * * `Sleuth` - Sleuth
         * * `Smartlook` - Smartlook
         * * `Smartrecruiters` - Smartrecruiters
         * * `Smokeball` - Smokeball
         * * `SodaCloud` - SodaCloud
         * * `Speedcurve` - Speedcurve
         * * `SpotIo` - SpotIo
         * * `Sprig` - Sprig
         * * `Sprinklr` - Sprinklr
         * * `SproutSocial` - SproutSocial
         * * `StackOverflowForTeams` - StackOverflowForTeams
         * * `Stockx` - Stockx
         * * `TackleIo` - TackleIo
         * * `Talkdesk` - Talkdesk
         * * `TeamupFitness` - TeamupFitness
         * * `Tebra` - Tebra
         * * `Telnyx` - Telnyx
         * * `Ternary` - Ternary
         * * `Thoughtspot` - Thoughtspot
         * * `Thousandeyes` - Thousandeyes
         * * `Threads` - Threads
         * * `TiktokShop` - TiktokShop
         * * `TinyErp` - TinyErp
         * * `Tinybird` - Tinybird
         * * `Tipalti` - Tipalti
         * * `Toast` - Toast
         * * `Torii` - Torii
         * * `Transistor` - Transistor
         * * `TrunkIo` - TrunkIo
         * * `Trustradius` - Trustradius
         * * `Twitch` - Twitch
         * * `TwoC2p` - TwoC2p
         * * `UkCompaniesHouse` - UkCompaniesHouse
         * * `UkOns` - UkOns
         * * `UnComtrade` - UnComtrade
         * * `UsBea` - UsBea
         * * `UsBls` - UsBls
         * * `UsEia` - UsEia
         * * `UsTreasuryFiscalData` - UsTreasuryFiscalData
         * * `Vanta` - Vanta
         * * `Vendr` - Vendr
         * * `Virtuous` - Virtuous
         * * `Vonage` - Vonage
         * * `WalmartMarketplace` - WalmartMarketplace
         * * `Waydev` - Waydev
         * * `Wayfair` - Wayfair
         * * `WhatsappBusinessManagement` - WhatsappBusinessManagement
         * * `WhoGho` - WhoGho
         * * `Whop` - Whop
         * * `Wiz` - Wiz
         * * `Wompi` - Wompi
         * * `Workiz` - Workiz
         * * `WorldBank` - WorldBank
         * * `Xendit` - Xendit
         * * `Yoco` - Yoco
         * * `ZalandoZdirect` - ZalandoZdirect
         * * `Zluri` - Zluri
         * * `Zylo` - Zylo
         * * `Tally` - Tally
         * * `Nuntly` - Nuntly
         * * `Vturb` - Vturb
         * * `Meltwater` - Meltwater
         * * `UserCom` - UserCom
         * * `Latitude` - Latitude
         * * `Workato` - Workato
         * * `SideShift` - SideShift
         * * `DuckLake` - DuckLake
         * * `Starburst` - Starburst
         * * `Trino` - Trino
         * * `Easybill` - Easybill
         * * `Bexio` - Bexio
         * * `Umami` - Umami
         * * `Manychat` - Manychat
         * * `Kickstarter` - Kickstarter
         * * `Typesense` - Typesense
         * * `FirstPromoter` - FirstPromoter
         * * `Zero` - Zero
         * * `Inth` - Inth
         * * `BCMS` - BCMS
         * * `Convonite` - Convonite
         * * `Hookdeck` - Hookdeck
         * * `Billit` - Billit
         * * `Moxie` - Moxie
         * * `TripleWhale` - TripleWhale
         * * `Directus` - Directus
         * * `Clay` - Clay
         * * `TradableBits` - TradableBits
         * * `Swan` - Swan
         * * `Hyros` - Hyros
         * * `Odoo` - Odoo
         * * `Airbridge` - Airbridge
         * * `Snovio` - Snovio
         * * `GoogleMerchantCenter` - GoogleMerchantCenter
         * * `Raisely` - Raisely
         * * `RakutenAdvertising` - RakutenAdvertising
         * * `Zitadel` - Zitadel
         * * `DeelFlows` - DeelFlows
         * * `WindsorAi` - WindsorAi
         * * `Wix` - Wix
         * * `Sevalla` - Sevalla
         * * `Motion` - Motion
         * * `ImpactPartner` - ImpactPartner
         * * `Cloudinary` - Cloudinary
         * * `Uploadcare` - Uploadcare
         * * `WHMCS` - WHMCS
         * * `MSG91` - MSG91
         * * `Depot` - Depot
         * * `Schematic` - Schematic
         * * `Dokploy` - Dokploy
         * * `Hootsuite` - Hootsuite
         * * `WisprFlow` - WisprFlow
         * * `SamCart` - SamCart
         * * `IronSourceAds` - IronSourceAds
         * * `MicrosoftExcel` - MicrosoftExcel
         * * `Profound` - Profound
         * * `Airwallex` - Airwallex
         * * `Polymarket` - Polymarket
         * * `Kalshi` - Kalshi
         * * `Capterra` - Capterra
         * * `GooglePostmasterTools` - GooglePostmasterTools
         * * `Growi` - Growi
         * * `Clarify` - Clarify
         * * `DatoCMS` - DatoCMS
         * * `WPSOffice` - WPSOffice
         * * `TeraBox` - TeraBox
         * * `SimonData` - SimonData
         * * `CommissionJunction` - CommissionJunction
         * * `Liveblocks` - Liveblocks
         * * `NationBuilder` - NationBuilder
         * * `Tana` - Tana
         * * `Zenchef` - Zenchef
         * * `Lovable` - Lovable
         * * `Anvil` - Anvil
         * * `Coolify` - Coolify
         * * `SocialPilot` - SocialPilot
         * * `Strato` - Strato
         * * `Medusa` - Medusa
         * * `Membrain` - Membrain
         * * `RecallAI` - RecallAI
         */
        source_type: ExternalDataSourceTypeEnum;
        /**
         * Connection credentials. Keys depend on source_type. Add a 'schemas' array to pick which tables sync; omit it and every discovered table syncs with default settings.
         */
        payload: Record<string, unknown>;
        prefix?: (string | null) | undefined;
        description?: (string | null) | undefined;
        access_method?:
            | (ExternalDataSourceAccessMethodEnum & unknown)
            | undefined;
        created_via?:
            | (ExternalDataSourceCreateCreatedViaEnum & unknown)
            | undefined;
        direct_query_enabled?: boolean | undefined;
        destination_ids?: Array<string> | undefined;
    };
    export type ExternalDataSourceCreateResponse = {
        /**
         * ID of the created external data source.
         */
        id: string;
    };
    /**
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp
     * * `wizard` - wizard
     * * `self_driving` - self_driving
     */
    export type ExternalDataSourceCreatedViaEnum =
        | "web"
        | "api"
        | "mcp"
        | "wizard"
        | "self_driving";
    export type ExternalDataSourceRevenueAnalyticsConfig = Partial<{
        enabled: boolean;
        include_invoiceless_charges: boolean;
    }>;
    /**
     * Mixin for serializers to add user access control fields
     */
    export type ExternalDataSourceSerializers = {
        id: string;
        created_at: string;
        created_by: string | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        created_via?: (ExternalDataSourceCreatedViaEnum | NullEnum) | undefined;
        status: string;
        client_secret: string;
        account_id: string;
        source_type: ExternalDataSourceTypeEnum & unknown;
        latest_error: string | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        prefix?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        description?: (string | null) | undefined;
        access_method: ExternalDataSourceAccessMethodEnum & unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        direct_query_enabled?: boolean | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        auto_sync_new_schemas?: boolean | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        auto_sync_schema_patterns?: (Array<string> | null) | undefined;
        /**
         * Backend engine detected for the direct connection.
         *
         * * `duckdb` - duckdb
         * * `postgres` - postgres
         * * `mysql` - mysql
         * * `snowflake` - snowflake
         * * `redshift` - redshift
         * * `clickhouse` - clickhouse
         * * `motherduck` - motherduck
         * * `trino` - trino
         */
        engine: EngineEnum | NullEnum;
        last_run_at: string | null;
        schemas: Array<Record<string, unknown>>;
        /**
         * Mixin for serializers to add user access control fields
         */
        job_inputs?: unknown | undefined;
        revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfig &
            unknown;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        supports_webhooks: boolean;
        /**
         * Whether this source supports per-column sync selection via `enabled_columns`.
         */
        supports_column_selection: boolean;
        /**
         * Vendor API version this source is pinned to (an opaque vendor label, e.g. a Stripe date version). Null resolves to the source type's default version at sync time.
         */
        api_version: string | null;
        /**
         * Set when the vendor has deprecated the API version this source is pinned to; null otherwise. Drives the in-product deprecation warning.
         */
        api_version_deprecation: ExternalDataSourceApiVersionDeprecation | null;
    };
    export type FeatureFlagExperimentSetMetadata = {
        /**
         * ID of the experiment linked to this flag.
         */
        id: number;
        /**
         * Name of the experiment linked to this flag.
         */
        name: string;
        /**
         * Whether the experiment is currently running (started and not yet stopped). A running experiment blocks deletion of the linked flag.
         */
        is_running: boolean;
    };
    /**
     * * `feature_flags` - feature_flags
     * * `experiments` - experiments
     * * `surveys` - surveys
     * * `early_access_features` - early_access_features
     * * `web_experiments` - web_experiments
     * * `product_tours` - product_tours
     */
    export type FeatureFlagCreationContextEnum =
        | "feature_flags"
        | "experiments"
        | "surveys"
        | "early_access_features"
        | "web_experiments"
        | "product_tours";
    /**
     * Serializer mixin that handles tags for objects.
     */
    export type FeatureFlag = {
        id: number;
        /**
         * Serializer mixin that handles tags for objects.
         */
        name?: string | undefined;
        key: string;
        /**
         * Serializer mixin that handles tags for objects.
         */
        filters?: Record<string, unknown> | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        deleted?: boolean | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        active?: boolean | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        archived?: boolean | undefined;
        created_by: UserBasic & unknown;
        /**
         * Serializer mixin that handles tags for objects.
         */
        created_at?: string | undefined;
        updated_at: string | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        version?: number | undefined;
        last_modified_by: UserBasic & unknown;
        /**
         * Serializer mixin that handles tags for objects.
         */
        ensure_experience_continuity?: (boolean | null) | undefined;
        experiment_set: Array<number>;
        experiment_set_metadata: Array<FeatureFlagExperimentSetMetadata>;
        surveys: Record<string, unknown>;
        features: Record<string, unknown>;
        can_edit: boolean;
        /**
         * Serializer mixin that handles tags for objects.
         */
        tags?: Array<unknown> | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        evaluation_contexts?: Array<unknown> | undefined;
        /**
         * Dashboard of saved usage insights for this flag, or null if it has none. Flags do not get one on creation; create it with POST /api/projects/{project_id}/feature_flags/{id}/dashboard/.
         */
        usage_dashboard: number | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        analytics_dashboards?: Array<number> | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        has_enriched_analytics?: (boolean | null) | undefined;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        /**
         * Serializer mixin that handles tags for objects.
         */
        creation_context?:
            | (FeatureFlagCreationContextEnum & unknown)
            | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        is_remote_configuration?: (boolean | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        has_encrypted_payloads?: (boolean | null) | undefined;
        status: string;
        /**
         * Serializer mixin that handles tags for objects.
         */
        evaluation_runtime?:
            | (EvaluationRuntimeEnum | BlankEnum | NullEnum)
            | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        bucketing_identifier?:
            | (BucketingIdentifierEnum | BlankEnum | NullEnum)
            | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        last_called_at?: (string | null) | undefined;
        /**
         * Serializer mixin that handles tags for objects.
         */
        _create_in_folder?: string | undefined;
        /**
         * Check if this feature flag is used in any team's session recording linked flag setting.
         */
        is_used_in_replay_settings: boolean;
        /**
         * Whether this flag can back an experiment: multivariate with 2 to 20 variants.
         */
        is_eligible_for_experiment: boolean;
    };
    export type FeatureFlagMultivariateVariantSchema = {
        /**
         * Unique key for this variant.
         */
        key: string;
        name?: string | undefined;
        /**
         * Variant rollout percentage.
         */
        rollout_percentage: number;
    };
    export type FeatureFlagMultivariateSchema = {
        /**
         * Variant definitions for multivariate feature flags.
         */
        variants: Array<FeatureFlagMultivariateVariantSchema>;
    };
    export type FeatureFlagFiltersSchema = Partial<{
        groups: Array<FeatureFlagConditionGroupSchema>;
        multivariate: FeatureFlagMultivariateSchema | null;
        aggregation_group_type_index: number | null;
        payloads: Record<string, string>;
        feature_enrollment: boolean | null;
        early_exit: boolean;
    }>;
    export type FeatureFlagCreateRequestSchema = Partial<{
        key: string;
        name: string;
        filters: FeatureFlagFiltersSchema;
        active: boolean;
        archived: boolean;
        tags: Array<string>;
        evaluation_contexts: Array<string>;
        is_remote_configuration: boolean | null;
        ensure_experience_continuity: boolean | null;
        evaluation_runtime: EvaluationRuntimeEnum | NullEnum;
        bucketing_identifier: BucketingIdentifierEnum | NullEnum;
    }>;
    export type FeatureFlagRolloutSummary = {
        /**
         * True if the flag is effectively rolled out to everyone, independent of recent evaluation. For boolean flags this means at least one release condition targets 100% with no property filters (or there are no release conditions); for multivariate flags it means a single variant is served to 100% via a fully rolled out release condition. This is the signal for 'fully rolled out' / GA — unlike `status`, which only reflects recent evaluation.
         */
        effectively_full_rollout: boolean;
        /**
         * True if any release condition has property filters, i.e. the flag is conditionally targeted rather than a blanket rollout. When true, `max_rollout_percentage` is a percentage within the targeted segment, not of the whole user base.
         */
        has_targeting_conditions: boolean;
        /**
         * Highest rollout percentage (0-100) across the flag's release conditions, treating a missing percentage as 100. Null when the flag has no release conditions. Interpret together with `has_targeting_conditions`.
         */
        max_rollout_percentage: number | null;
        /**
         * True if the flag serves multiple variants (has a multivariate variant set).
         */
        is_multivariate: boolean;
    };
    export type FeatureFlagStatusResponse = {
        /**
         * Flag staleness/evaluation status: active, stale, archived, deleted, or unknown. 'active' means the flag was recently evaluated (or has no usage data yet) — it does NOT mean the flag is fully rolled out. Use the `rollout` object to determine rollout completeness.
         */
        status: string;
        /**
         * Human-readable explanation of the status
         */
        reason: string;
        /**
         * Summary of the flag's rollout configuration, for determining whether it is fully rolled out.
         */
        rollout: FeatureFlagRolloutSummary;
    };
    /**
     * * `draft` - Draft
     * * `active` - Active
     * * `archived` - Archived
     */
    export type HogFlowStateEnum = "draft" | "active" | "archived";
    /**
     * * `loops` - Loops
     */
    export type HogFlowOriginProductEnum = "loops";
    export type HogFlowMasking = {
        ttl?: (number | null) | undefined;
        threshold?: (number | null) | undefined;
        /**
         * HogQL template defining the dedup/grouping key, e.g. '{person.id}' (once per person) within ttl.
         */
        hash: string;
        bytecode?: unknown | undefined;
    };
    /**
     * * `events` - events
     * * `internal-events` - internal-events
     * * `person-updates` - person-updates
     * * `data-warehouse-table` - data-warehouse-table
     * * `data-warehouse-view` - data-warehouse-view
     */
    export type HogFunctionFiltersSourceEnum =
        | "events"
        | "internal-events"
        | "person-updates"
        | "data-warehouse-table"
        | "data-warehouse-view";
    export type HogFunctionFilters = Partial<{
        source: HogFunctionFiltersSourceEnum & unknown;
        actions: Array<Record<string, unknown>>;
        events: Array<Record<string, unknown>>;
        data_warehouse: Array<Record<string, unknown>>;
        properties: Array<Record<string, unknown>>;
        bytecode: unknown;
        transpiled: unknown;
        filter_test_accounts: boolean;
        bytecode_error: string;
    }>;
    export type HogFlowConversionEvent = {
        /**
         * Event/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side.
         */
        filters: HogFunctionFilters;
    };
    export type HogFlowConversion = Partial<{
        filters: Array<Record<string, unknown>>;
        events: Array<HogFlowConversionEvent>;
        window_minutes: number | null;
        bytecode: unknown;
    }>;
    /**
     * * `minute` - minute
     * * `hour` - hour
     */
    export type PeriodEnum = "minute" | "hour";
    export type HogFlowEmailSendingRateLimit = {
        /**
         * Maximum number of emails this workflow sends per period.
         */
        count: number;
        /**
         * Window the count applies to. Sends over the limit are delayed until capacity frees up, not dropped.
         *
         * * `minute` - minute
         * * `hour` - hour
         */
        period: PeriodEnum;
    };
    /**
     * * `continue` - continue
     * * `branch` - branch
     */
    export type HogFlowEdgeTypeEnum = "continue" | "branch";
    export type HogFlowEdge = {
        /**
         * Target action id.
         */
        to: string;
        /**
         * continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].
         *
         * * `continue` - continue
         * * `branch` - branch
         */
        type: HogFlowEdgeTypeEnum;
        index?: number | undefined;
        /**
         * Source action id.
         */
        from: string;
    };
    /**
     * * `continue` - continue
     * * `abort` - abort
     */
    export type OnErrorEnum = "continue" | "abort";
    /**
     * * `trigger` - trigger
     * * `function` - function
     * * `function_email` - function_email
     * * `function_sms` - function_sms
     * * `function_push` - function_push
     * * `delay` - delay
     * * `wait_until_condition` - wait_until_condition
     * * `wait_until_time_window` - wait_until_time_window
     * * `conditional_branch` - conditional_branch
     * * `random_cohort_branch` - random_cohort_branch
     * * `exit` - exit
     */
    export type HogFlowActionTypeEnum =
        | "trigger"
        | "function"
        | "function_email"
        | "function_sms"
        | "function_push"
        | "delay"
        | "wait_until_condition"
        | "wait_until_time_window"
        | "conditional_branch"
        | "random_cohort_branch"
        | "exit";
    export type HogFlowAction = {
        /**
         * Unique node ID within the workflow.
         */
        id: string;
        /**
         * Display name.
         */
        name: string;
        description?: string | undefined;
        on_error?: (OnErrorEnum | NullEnum) | undefined;
        created_at?: number | undefined;
        updated_at?: number | undefined;
        filters?: (HogFunctionFilters | null) | undefined;
        /**
         * One of: trigger | function | function_email | function_sms | function_push | delay | wait_until_condition | wait_until_time_window | conditional_branch | random_cohort_branch | exit.
         *
         * * `trigger` - trigger
         * * `function` - function
         * * `function_email` - function_email
         * * `function_sms` - function_sms
         * * `function_push` - function_push
         * * `delay` - delay
         * * `wait_until_condition` - wait_until_condition
         * * `wait_until_time_window` - wait_until_time_window
         * * `conditional_branch` - conditional_branch
         * * `random_cohort_branch` - random_cohort_branch
         * * `exit` - exit
         */
        type: HogFlowActionTypeEnum;
        /**
         * Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel|internal-event, filters?}. internal-event requires filters.events naming one or more allowed event ids, and runs once for each matching event on the internal-events stream. Runs are person-less, so person-dependent steps are rejected. $slack_message_received takes filters: {properties: [<cond>]} over the message properties (channel, user, bot_id, text, subtype, is_thread_reply), and requires an exact-match channel filter; without one it runs on every message in every connected channel. $github_event_received takes filters: {properties: [<cond>]} over the delivery properties (repository, event_type, action, sender, bot_sender, own_app, author_association, actor_access, title, body, review_state, branch, repository_visibility), and requires exact-match repository and event_type filters; without them it runs on every delivery from every connected repository. webhook and manual triggers also require template_id: 'template-source-webhook', and tracking_pixel requires template_id: 'template-source-webhook-pixel'. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}, or {key: 'id', type: 'cohort', value: <cohort_id>, operator: 'in'} to reference a cohort. batch triggers may set filters.audience_type: 'persons' (default) or 'accounts'. An accounts audience fans out one run per customer analytics account and takes account filters instead: properties entries of type 'account_custom_property' (key = definition id), plus tag_names: [<str>], assigned_to_user_ids: [<int>], all_roles_unassigned: <bool>. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. function_email also accepts tracking_enabled?: <bool> (default true) - when false, no open pixel is injected, links are not rewritten, and the send skips ESP-level open/click tracking, so opens and clicks are not recorded for that step (delivery/bounce/unsubscribe still are). Dictionary input values are template strings too — write booleans/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: waits a fixed span or until a per-person/-event date — set EXACTLY ONE of delay_duration or delay_until. {delay_duration: '<number><unit>'} where unit is s|m|h|d. Fractions OK ('1.5d'=36h). Per-unit max s<=60, m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. delay_until: {expression: '<SQL>', offset?: '<±number><unit>'} waits until the date expression evaluates to (an ISO string, unix seconds, or a date value all resolve to the same instant); offset is a signed duration shifting it ('-1d' a day before, '2h' two hours after). expression is compiled server-side, so any bytecode sent with it is discarded. A person property is person.properties.<key>; an event property is properties.<key>, as the 'event.' prefix resolves to nothing and aborts the run. Optional timezone (IANA name), use_person_timezone (read $geoip_time_zone) and fallback_timezone decide which zone a date with no offset of its own is read in; a date that states an offset, and unix seconds, ignore them. Default UTC. Optional sibling max_delay_duration (default 30d, same '<number><unit>' format) caps how far past the step's start the wait may run. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. random_cohort_branch: {cohorts: [{percentage: <number>, name?}, ...]}. Index N matches the 'branch' edge with index:N; percentages are relative weights, so they should sum to 100 but a total above or below that still splits traffic in the given proportions. wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as delay). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}.
         */
        config:
            | Record<string, unknown>
            | {
                  /**
                   * Config for type='wait_until_condition'. Provide 'condition' and/or 'events' — an events-only wait (no condition) is valid.
                   */
                  condition?:
                      | Partial<{
                            /**
                             * Property conditions, e.g. {properties: [{key, value, operator, type}]}.
                             */
                            filters: HogFunctionFilters | null;
                            /**
                             * Optional display name.
                             */
                            name: string;
                        }>
                      | undefined;
                  /**
                   * Config for type='wait_until_condition'. Provide 'condition' and/or 'events' — an events-only wait (no condition) is valid.
                   */
                  events?:
                      | Array<
                            Partial<{
                                /**
                                 * Event/action filters; the workflow wakes when a matching event fires. Must target at least one event or action (entries targeting neither are dropped).
                                 */
                                filters: HogFunctionFilters | null;
                                /**
                                 * Optional display name.
                                 */
                                name: string;
                            }>
                        >
                      | undefined;
                  /**
                   * '<number><unit>' with unit s|m|h|d, e.g. '30m' (same rules as delay).
                   */
                  max_wait_duration: string;
              };
        output_variable?: unknown | undefined;
    };
    /**
     * * `active` - Active
     * * `paused` - Paused
     * * `completed` - Completed
     */
    export type HogFlowScheduleStatusEnum = "active" | "paused" | "completed";
    export type HogFlowSchedule = {
        id: string;
        /**
         * iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour.
         */
        rrule: string;
        /**
         * ISO 8601 datetime the schedule starts from.
         */
        starts_at: string;
        timezone?: string | undefined;
        variables?: unknown | undefined;
        /**
         * active, paused, or completed (set once the RRULE's COUNT/UNTIL is exhausted).
         *
         * * `active` - Active
         * * `paused` - Paused
         * * `completed` - Completed
         */
        status: HogFlowScheduleStatusEnum & unknown;
        /**
         * Next scheduled fire time, computed by the scheduler.
         */
        next_run_at: string | null;
        created_at: string;
        updated_at: string;
    };
    /**
     * Mixin for serializers to add user access control fields
     */
    export type HogFlow = {
        id: string;
        /**
         * Mixin for serializers to add user access control fields
         */
        name?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        description?: string | undefined;
        version: number;
        /**
         * Mixin for serializers to add user access control fields
         */
        status?: HogFlowStateEnum | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        origin_product?: (HogFlowOriginProductEnum | NullEnum) | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        updated_at: string;
        trigger: unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        trigger_masking?: (HogFlowMasking | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        conversion?: (HogFlowConversion | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        exit_condition?: ExitConditionEnum | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        email_sending_rate_limit?:
            | (HogFlowEmailSendingRateLimit | null)
            | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        edges?: Array<HogFlowEdge> | undefined;
        /**
         * Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too.
         */
        actions: Array<HogFlowAction>;
        abort_action: string | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        variables?: Array<Record<string, string>> | undefined;
        billable_action_types: unknown;
        /**
         * Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows.
         */
        schedules: Array<HogFlowSchedule>;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        /**
         * Staged content changes awaiting publish — a full snapshot of the workflow's actions, edges and settings. Null when there's nothing staged. Test it with a use_draft test run, then promote it with the publish endpoint or throw it away with discard_draft.
         */
        draft: unknown;
        /**
         * When the draft was last written; null when there's no staged draft. Pass this to publish (and as base_updated_at on further draft edits) so a concurrent editor's changes aren't clobbered — a mismatch returns 409.
         */
        draft_updated_at: string | null;
        /**
         * Skip-forward map for deleted steps: {deleted_action_id: next surviving action_id}. Maintained automatically when a live graph edit deletes actions, so in-flight runs parked on a deleted step continue at its surviving successor instead of exiting. Null when no live deletions have occurred.
         */
        action_redirects: Record<string, string> | null;
    };
    /**
     * Mixin for serializers to add user access control fields
     */
    export type HogFlowMinimal = {
        id: string;
        name: string | null;
        description: string;
        version: number;
        status: HogFlowStateEnum & unknown;
        origin_product: HogFlowOriginProductEnum | NullEnum;
        created_at: string;
        created_by: UserBasic & unknown;
        updated_at: string;
        trigger: unknown;
        trigger_masking: unknown;
        conversion: unknown;
        exit_condition: ExitConditionEnum & unknown;
        email_sending_rate_limit: unknown;
        edges: unknown;
        actions: unknown;
        abort_action: string | null;
        variables: unknown;
        billable_action_types: unknown;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    export type HogFlowRunRequest = Partial<{
        variables: Record<string, unknown>;
    }>;
    export type HogFlowRunResponse = {
        /**
         * 'queued' once the invocation has been queued for execution.
         */
        status: string;
        /**
         * ID of the queued hog flow invocation.
         */
        invocation_id: string;
    };
    /**
     * Mixin for serializers to add user access control fields
     */
    export type HogFlowUpdate = {
        id: string;
        /**
         * Mixin for serializers to add user access control fields
         */
        name?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        description?: string | undefined;
        version: number;
        /**
         * Mixin for serializers to add user access control fields
         */
        status?: HogFlowStateEnum | undefined;
        /**
         * Product surface that owns this workflow. This value cannot change after creation.
         *
         * * `loops` - Loops
         */
        origin_product: HogFlowOriginProductEnum | NullEnum;
        created_at: string;
        created_by: UserBasic & unknown;
        updated_at: string;
        trigger: unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        trigger_masking?: (HogFlowMasking | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        conversion?: (HogFlowConversion | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        exit_condition?: ExitConditionEnum | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        email_sending_rate_limit?:
            | (HogFlowEmailSendingRateLimit | null)
            | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        edges?: Array<HogFlowEdge> | undefined;
        /**
         * Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too.
         */
        actions: Array<HogFlowAction>;
        abort_action: string | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        variables?: Array<Record<string, string>> | undefined;
        billable_action_types: unknown;
        /**
         * Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows.
         */
        schedules: Array<HogFlowSchedule>;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        /**
         * Staged content changes awaiting publish — a full snapshot of the workflow's actions, edges and settings. Null when there's nothing staged. Test it with a use_draft test run, then promote it with the publish endpoint or throw it away with discard_draft.
         */
        draft: unknown;
        /**
         * When the draft was last written; null when there's no staged draft. Pass this to publish (and as base_updated_at on further draft edits) so a concurrent editor's changes aren't clobbered — a mismatch returns 409.
         */
        draft_updated_at: string | null;
        /**
         * Skip-forward map for deleted steps: {deleted_action_id: next surviving action_id}. Maintained automatically when a live graph edit deletes actions, so in-flight runs parked on a deleted step continue at its surviving successor instead of exiting. Null when no live deletions have occurred.
         */
        action_redirects: Record<string, string> | null;
    };
    export type HogQueryResponse = {
        bytecode?: (Array<unknown> | null) | undefined;
        coloredBytecode?: (Array<unknown> | null) | undefined;
        results: unknown;
        stdout?: (string | null) | undefined;
    };
    export type HogQuery = Partial<{
        code: string | null;
        kind: string;
        modifiers: HogQLQueryModifiers | null;
        response: HogQueryResponse | null;
        tags: QueryLogTags | null;
        version: number | null;
    }>;
    /**
     * * `http` - http
     * * `sse` - sse
     */
    export type ImportedMcpServerTypeEnum = "http" | "sse";
    export type ImportedMcpServerHeader = { name: string; value: string };
    /**
     * One client-imported MCP server, in the agent server's --mcpServers entry shape.
     */
    export type ImportedMcpServer = {
        type: ImportedMcpServerTypeEnum;
        name: string;
        url: string;
        /**
         * One client-imported MCP server, in the agent server's --mcpServers entry shape.
         */
        headers?: Array<ImportedMcpServerHeader> | undefined;
    };
    export type RETENTION = Partial<{
        hideLineGraph: boolean | null;
        hideSizeColumn: boolean | null;
        useSmallLayout: boolean | null;
    }>;
    export type VizSpecificOptions = Partial<{
        ActionsPie: ActionsPie | null;
        RETENTION: RETENTION | null;
    }>;
    export type InsightVizNode = {
        embedded?: (boolean | null) | undefined;
        full?: (boolean | null) | undefined;
        hidePersonsModal?: (boolean | null) | undefined;
        hideTooltipOnScroll?: (boolean | null) | undefined;
        kind?: string | undefined;
        showCorrelationTable?: (boolean | null) | undefined;
        showFilters?: (boolean | null) | undefined;
        showHeader?: (boolean | null) | undefined;
        showLastComputation?: (boolean | null) | undefined;
        showLastComputationRefresh?: (boolean | null) | undefined;
        showResults?: (boolean | null) | undefined;
        showTable?: (boolean | null) | undefined;
        source:
            | TrendsQuery
            | FunnelsQuery
            | RetentionQuery
            | PathsQuery
            | PathsV2Query
            | StickinessQuery
            | LifecycleQuery
            | WebStatsTableQuery
            | WebOverviewQuery;
        suppressSessionAnalysisWarning?: (boolean | null) | undefined;
        version?: (number | null) | undefined;
        vizSpecificOptions?: (VizSpecificOptions | null) | undefined;
    };
    /**
     * The query definition for this insight. The `kind` field determines the query type:
     * - `InsightVizNode` — product analytics (trends, funnels, retention, paths, stickiness, lifecycle)
     * - `DataVisualizationNode` — SQL insights using HogQL
     * - `DataTableNode` — raw data tables
     * - `HogQuery` — Hog language queries
     */
    export type _InsightQuerySchema =
        | InsightVizNode
        | DataTableNode
        | DataVisualizationNode
        | HogQuery;
    export type TileFilters = Partial<{
        breakdown_filter: BreakdownFilter | null;
        date_from: string | null;
        date_to: string | null;
        explicitDate: boolean | null;
        filterTestAccounts: boolean | null;
        ignoreDashboardFilters: boolean | null;
        interval: IntervalType | null;
        properties: Array<
            | EventPropertyFilter
            | PersonPropertyFilter
            | PersonMetadataPropertyFilter
            | ElementPropertyFilter
            | EventMetadataPropertyFilter
            | SessionPropertyFilter
            | CohortPropertyFilter
            | RecordingPropertyFilter
            | LogEntryPropertyFilter
            | GroupPropertyFilter
            | FeaturePropertyFilter
            | FlagPropertyFilter
            | HogQLPropertyFilter
            | EmptyPropertyFilter
            | DataWarehousePropertyFilter
            | DataWarehousePersonPropertyFilter
            | ErrorTrackingIssueFilter
            | LogPropertyFilter
            | MetricPropertyFilter
            | SpanPropertyFilter
            | RevenueAnalyticsPropertyFilter
            | AccountCustomPropertyFilter
            | WorkflowVariablePropertyFilter
            | BehavioralPropertyFilter
        > | null;
    }>;
    export type InsightFilterOverrideContext = Partial<{
        dashboard: DashboardFilter | null;
        tile: TileFilters | null;
        overridden_dashboard: DashboardFilter | null;
    }>;
    /**
     * Simplified serializer to speed response times when loading large amounts of objects.
     */
    export type Insight = {
        id: number;
        short_id: string;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        name?: (string | null) | undefined;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        derived_name?: (string | null) | undefined;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        query?: (_InsightQuerySchema | null) | undefined;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        order?: (number | null) | undefined;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        deleted?: boolean | undefined;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        dashboards?: Array<number> | undefined;
        /**
         * A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
         */
        dashboard_tiles: Array<DashboardTileBasic>;
        /**
         * The datetime this insight's results were generated.
         *     If added to one or more dashboards the insight can be refreshed separately on each.
         *     Returns the appropriate last_refresh datetime for the context the insight is viewed in
         *     (see from_dashboard query parameter).
         */
        last_refresh: string | null;
        /**
         * The target age of the cached results for this insight.
         */
        cache_target_age: string | null;
        /**
         * The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
         *     by querying the database.
         */
        next_allowed_client_refresh: string | null;
        result: unknown;
        hasMore: boolean | null;
        columns: Array<string> | null;
        created_at: string | null;
        created_by: UserBasic & unknown;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        description?: (string | null) | undefined;
        updated_at: string;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        tags?: Array<unknown> | undefined;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        favorited?: boolean | undefined;
        last_modified_at: string;
        last_modified_by: UserBasic & unknown;
        is_sample: boolean;
        effective_restriction_level: RestrictionLevelEnum & unknown;
        effective_privilege_level: PrivilegeLevelEnum & unknown;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        /**
         * The timezone this chart is displayed in.
         */
        timezone: string | null;
        is_cached: boolean;
        query_status: unknown;
        hogql: string | null;
        types: Array<unknown> | null;
        resolved_date_range: Partial<{
            date_from: string;
            date_to: string;
        }> | null;
        /**
         * Simplified serializer to speed response times when loading large amounts of objects.
         */
        _create_in_folder?: string | undefined;
        alerts: Array<unknown>;
        /**
         * Resolved dashboard and tile filter layers used to explain filter precedence in the UI.
         */
        filter_override_context: InsightFilterOverrideContext | null;
        last_viewed_at: string | null;
        /**
         * How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.
         */
        search_match_type: SearchMatchTypeEnum | NullEnum;
    };
    /**
     * * `connected` - connected
     * * `unavailable` - unavailable
     */
    export type InstallationStatusEnum = "connected" | "unavailable";
    /**
     * * `anthropic` - Anthropic
     * * `apns` - Apple Push
     * * `aws-redshift` - Aws Redshift
     * * `aws-s3` - Aws S3
     * * `azure-blob` - Azure Blob
     * * `bing-ads` - Bing Ads
     * * `clickup` - Clickup
     * * `customerio-app` - Customerio App
     * * `customerio-track` - Customerio Track
     * * `customerio-webhook` - Customerio Webhook
     * * `databricks` - Databricks
     * * `email` - Email
     * * `firebase` - Firebase
     * * `github` - Github
     * * `gitlab` - Gitlab
     * * `google-ads` - Google Ads
     * * `google-analytics` - Google Analytics
     * * `google-calendar` - Google Calendar
     * * `google-cloud-service-account` - Google Cloud Service Account
     * * `google-cloud-storage` - Google Cloud Storage
     * * `google-pubsub` - Google Pubsub
     * * `google-search-console` - Google Search Console
     * * `google-sheets` - Google Sheets
     * * `hubspot` - Hubspot
     * * `instagram` - Instagram
     * * `intercom` - Intercom
     * * `jira` - Jira
     * * `linear` - Linear
     * * `linkedin-ads` - Linkedin Ads
     * * `meta-ads` - Meta Ads
     * * `pardot` - Pardot
     * * `pinterest-ads` - Pinterest Ads
     * * `postgresql` - Postgresql
     * * `posthog` - Posthog
     * * `reddit-ads` - Reddit Ads
     * * `resend` - Resend
     * * `s3-compatible` - S3 Compatible
     * * `salesforce` - Salesforce
     * * `slack` - Slack
     * * `slack-posthog-code` - Slack Posthog Code
     * * `snapchat` - Snapchat
     * * `snowflake` - Snowflake
     * * `stripe` - Stripe
     * * `tiktok-ads` - Tiktok Ads
     * * `twilio` - Twilio
     * * `vercel` - Vercel
     * * `youtube-analytics` - Youtube Analytics
     */
    export type IntegrationKindEnum =
        | "anthropic"
        | "apns"
        | "aws-redshift"
        | "aws-s3"
        | "azure-blob"
        | "bing-ads"
        | "clickup"
        | "customerio-app"
        | "customerio-track"
        | "customerio-webhook"
        | "databricks"
        | "email"
        | "firebase"
        | "github"
        | "gitlab"
        | "google-ads"
        | "google-analytics"
        | "google-calendar"
        | "google-cloud-service-account"
        | "google-cloud-storage"
        | "google-pubsub"
        | "google-search-console"
        | "google-sheets"
        | "hubspot"
        | "instagram"
        | "intercom"
        | "jira"
        | "linear"
        | "linkedin-ads"
        | "meta-ads"
        | "pardot"
        | "pinterest-ads"
        | "postgresql"
        | "posthog"
        | "reddit-ads"
        | "resend"
        | "s3-compatible"
        | "salesforce"
        | "slack"
        | "slack-posthog-code"
        | "snapchat"
        | "snowflake"
        | "stripe"
        | "tiktok-ads"
        | "twilio"
        | "vercel"
        | "youtube-analytics";
    /**
     * Standard Integration serializer.
     */
    export type IntegrationConfig = {
        id: number;
        kind: IntegrationKindEnum;
        /**
         * Standard Integration serializer.
         */
        config?: unknown | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        errors: string;
        display_name: string;
        /**
         * Slack only: whether reconnecting can request the files:write scope.
         */
        files_write_requestable: boolean;
        /**
         * GitHub only, null otherwise. Whether another project's GitHub integration references the same App installation. When false, disconnecting this integration also uninstalls the GitHub App from the connected account or organization and removes personal GitHub connections that share it.
         */
        installation_shared: boolean | null;
        /**
         * GitHub only, null otherwise. `unavailable` means the App was uninstalled or suspended on GitHub and PostHog can no longer mint tokens for it; `connected` otherwise.
         */
        installation_status: InstallationStatusEnum | NullEnum;
    };
    /**
     * * `burst` - burst
     * * `sustained` - sustained
     */
    export type LimitTypeEnum = "burst" | "sustained";
    /**
     * * `api_key` - API Key
     * * `oauth` - OAuth
     */
    export type MCPAuthTypeEnum = "api_key" | "oauth";
    /**
     * * `business` - Business Operations
     * * `data` - Data & Analytics
     * * `design` - Design & Content
     * * `dev` - Developer Tools & APIs
     * * `infra` - Infrastructure
     * * `productivity` - Productivity & Collaboration
     */
    export type MCPServerCategoryEnum =
        | "business"
        | "data"
        | "design"
        | "dev"
        | "infra"
        | "productivity";
    /**
     * * `personal` - Personal
     * * `shared` - Shared
     */
    export type MCPServerInstallationScopeEnum = "personal" | "shared";
    export type MCPServerInstallation = {
        id: string;
        template_id: string | null;
        name: string;
        /**
         * Deprecated: use icon_domain instead. Lowercase key from the linked template for clients that still render bundled icon assets. Empty if custom install (no template).
         */
        icon_key: string;
        /**
         * Brand domain from the linked template, rendered via the logo.dev icon proxy. Empty if custom install (no template).
         */
        icon_domain: string;
        display_name?: string | undefined;
        url?: string | undefined;
        /**
         * Installation description, falling back to the linked template description.
         */
        description: string;
        auth_type?: MCPAuthTypeEnum | undefined;
        is_enabled?: boolean | undefined;
        scope: MCPServerInstallationScopeEnum & unknown;
        /**
         * True when the requesting user owns this installation. Lets clients gate owner-only controls instead of surfacing 403s.
         */
        is_owner: boolean;
        needs_reauth: boolean;
        pending_oauth: boolean;
        proxy_url: string;
        /**
         * Number of live (non-removed) tools exposed by this installation.
         */
        tool_count: number;
        created_at: string;
        updated_at: string | null;
    };
    /**
     * * `approved` - Approved
     * * `needs_approval` - Needs approval
     * * `do_not_use` - Do not use
     */
    export type MCPToolApprovalStateEnum =
        | "approved"
        | "needs_approval"
        | "do_not_use";
    export type MCPServerInstallationTool = {
        id: string;
        tool_name: string;
        display_name: string;
        description: string;
        input_schema: unknown;
        /**
         * Effective state after applying the team ceiling.
         */
        approval_state: MCPToolApprovalStateEnum & unknown;
        /**
         * Team-admin ceiling for this tool. Null when the team imposes no ceiling.
         */
        team_state: MCPToolApprovalStateEnum | NullEnum;
        /**
         * True when a rule or Blocked team ceiling leaves no editable state.
         */
        locked: boolean;
        /**
         * Policy layer that decided the effective state.
         */
        decided_by: string;
        last_seen_at: string;
        removed_at: string | null;
        created_at: string;
        updated_at: string | null;
    };
    export type MCPServerTemplate = {
        id: string;
        name: string;
        url: string;
        docs_url?: (string | string) | undefined;
        description?: string | undefined;
        auth_type?: MCPAuthTypeEnum | undefined;
        /**
         * Deprecated: use icon_domain instead. Lowercase key for clients that still render bundled icon assets.
         */
        icon_key: string;
        /**
         * The vendor's brand domain (e.g. 'linear.app'), resolved to an icon at render time via the logo.dev proxy endpoint. Empty when no brand icon is known.
         */
        icon_domain: string;
        category?: MCPServerCategoryEnum | undefined;
        is_coming_soon?: boolean | undefined;
    };
    /**
     * A conversion goal counted from an action.
     */
    export type MarketingAnalyticsActionConversionGoal = {
        conversion_goal_id: string;
        conversion_goal_name: string;
        /**
         * A conversion goal counted from an action.
         */
        counts_as_customer?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        counts_as_revenue?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        custom_name?: (string | null) | undefined;
        id: number;
        kind: string;
        /**
         * A conversion goal counted from an action.
         */
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        /**
         * A conversion goal counted from an action.
         */
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        math_hogql?: (string | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        math_multiplier?: (number | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        math_property?: (string | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        /**
         * A conversion goal counted from an action.
         */
        math_property_type?: (string | null) | undefined;
        name: string;
        /**
         * A conversion goal counted from an action.
         */
        optionalInFunnel?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from an action.
         */
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | CohortPropertyFilter
                  | ElementPropertyFilter
                  | HogQLPropertyFilter
                  | DataWarehousePropertyFilter
              > | null)
            | undefined;
        /**
         * A conversion goal counted from an action.
         */
        response?: (Record<string, unknown> | null) | undefined;
        schema_map: Record<string, string | unknown>;
        /**
         * A conversion goal counted from an action.
         */
        version?: (number | null) | undefined;
    };
    /**
     * Mapping of integration type to the campaign field used when matching campaigns.
     */
    export type MarketingAnalyticsCampaignFieldPreferences = Record<
        string,
        CampaignFieldPreference
    >;
    /**
     * Mapping of integration type to canonical campaign name to the aliases folded into it.
     */
    export type MarketingAnalyticsCampaignNameMappings = Record<
        string,
        Record<string, Array<string>>
    >;
    /**
     * A conversion goal counted from events.
     */
    export type MarketingAnalyticsEventConversionGoal = {
        conversion_goal_id: string;
        conversion_goal_name: string;
        /**
         * A conversion goal counted from events.
         */
        counts_as_customer?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        counts_as_revenue?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        custom_name?: (string | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        event?: (string | null) | undefined;
        kind: string;
        /**
         * A conversion goal counted from events.
         */
        limit?: (number | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        /**
         * A conversion goal counted from events.
         */
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        math_hogql?: (string | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        math_multiplier?: (number | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        math_property?: (string | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        /**
         * A conversion goal counted from events.
         */
        math_property_type?: (string | null) | undefined;
        name: string;
        /**
         * A conversion goal counted from events.
         */
        optionalInFunnel?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        orderBy?: (Array<string> | null) | undefined;
        /**
         * A conversion goal counted from events.
         */
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | CohortPropertyFilter
                  | ElementPropertyFilter
                  | HogQLPropertyFilter
                  | DataWarehousePropertyFilter
              > | null)
            | undefined;
        /**
         * A conversion goal counted from events.
         */
        response?: (Record<string, unknown> | null) | undefined;
        schema_map: Record<string, string | unknown>;
        /**
         * A conversion goal counted from events.
         */
        version?: (number | null) | undefined;
    };
    /**
     * A conversion goal counted from a data warehouse table.
     */
    export type MarketingAnalyticsWarehouseConversionGoal = {
        conversion_goal_id: string;
        conversion_goal_name: string;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        counts_as_customer?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        counts_as_revenue?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        custom_name?: (string | null) | undefined;
        distinct_id_field: string;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        dw_source_type?: (string | null) | undefined;
        id: string;
        id_field: string;
        kind: string;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | GroupMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | null
              )
            | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math_hogql?: (string | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math_multiplier?: (number | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math_property?: (string | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math_property_revenue_currency?:
            | (RevenueCurrencyPropertyConfig | null)
            | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        math_property_type?: (string | null) | undefined;
        name: string;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        optionalInFunnel?: (boolean | null) | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        properties?:
            | (Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | CohortPropertyFilter
                  | ElementPropertyFilter
                  | HogQLPropertyFilter
                  | DataWarehousePropertyFilter
              > | null)
            | undefined;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        response?: (Record<string, unknown> | null) | undefined;
        schema_map: Record<string, string | unknown>;
        table_name: string;
        timestamp_field: string;
        /**
         * A conversion goal counted from a data warehouse table.
         */
        version?: (number | null) | undefined;
    };
    /**
     * The conversion goals configured for marketing analytics, in display order.
     */
    export type MarketingAnalyticsConversionGoalList = Array<
        | MarketingAnalyticsEventConversionGoal
        | MarketingAnalyticsActionConversionGoal
        | MarketingAnalyticsWarehouseConversionGoal
    >;
    /**
     * Mapping of integration type to the custom UTM source values folded into it.
     */
    export type MarketingAnalyticsCustomSourceMappings = Record<
        string,
        Array<string>
    >;
    export type SourceMap = Partial<{
        ad_group_id: string | null;
        ad_group_name: string | null;
        ad_id: string | null;
        ad_name: string | null;
        campaign: string | null;
        clicks: string | null;
        cost: string | null;
        currency: string | null;
        date: string | null;
        id: string | null;
        impressions: string | null;
        reported_conversion: string | null;
        reported_conversion_value: string | null;
        source: string | null;
    }>;
    /**
     * Mapping of external data source id to that source's column mapping.
     */
    export type MarketingAnalyticsSourceMapping = Record<string, SourceMap>;
    export type MinimalPerson = {
        /**
         * Numeric person ID.
         */
        id: number;
        /**
         * Display name derived from person properties (email, name, or username).
         */
        name: string;
        distinct_ids: Array<string>;
        properties?: unknown | undefined;
        /**
         * When this person was first seen (ISO 8601).
         */
        created_at: string;
        /**
         * Unique identifier (UUID) for this person.
         */
        uuid: string;
        /**
         * Timestamp of the last event from this person, or null.
         */
        last_seen_at: string | null;
    };
    export type OAuthRedirectResponse = { redirect_url: string };
    /**
     * * `insight` - insight
     * * `hogql` - hogql
     * * `dashboard` - dashboard
     * * `error` - error
     * * `replay` - replay
     * * `flag` - flag
     * * `experiment` - experiment
     * * `survey` - survey
     * * `ticket` - ticket
     * * `trace` - trace
     * * `eval` - eval
     * * `event` - event
     * * `cohort` - cohort
     * * `action` - action
     * * `person` - person
     */
    export type ObjectKindEnum =
        | "insight"
        | "hogql"
        | "dashboard"
        | "error"
        | "replay"
        | "flag"
        | "experiment"
        | "survey"
        | "ticket"
        | "trace"
        | "eval"
        | "event"
        | "cohort"
        | "action"
        | "person";
    /**
     * * `delegated` - Delegated to teammate
     * * `later` - Skipped for later
     * * `other` - Other
     * * `provisioned` - Account provisioned by a partner
     */
    export type OnboardingSkippedReasonEnum =
        | "delegated"
        | "later"
        | "other"
        | "provisioned";
    /**
     * * `1` - member
     * * `8` - administrator
     * * `15` - owner
     */
    export type OrganizationMembershipLevelEnum = 1 | 8 | 15;
    /**
     * * `0` - none
     * * `3` - config
     * * `6` - install
     * * `9` - root
     */
    export type OrganizationPluginsAccessLevelEnum = 0 | 3 | 6 | 9;
    /**
     * * `bayesian` - Bayesian
     * * `frequentist` - Frequentist
     */
    export type OrganizationDefaultExperimentStatsMethodEnum =
        | "bayesian"
        | "frequentist";
    export type Organization = {
        id: string;
        name: string;
        slug: string;
        logo_media_id?: (string | null) | undefined;
        created_at: string;
        updated_at: string;
        membership_level: OrganizationMembershipLevelEnum & unknown;
        plugins_access_level: OrganizationPluginsAccessLevelEnum & unknown;
        teams: Array<Record<string, unknown>>;
        projects: Array<Record<string, unknown>>;
        available_product_features: Array<unknown> | null;
        /**
         * Legacy field; member-join emails are controlled per user in account notification settings.
         */
        is_member_join_email_enabled: boolean;
        metadata: Record<string, string>;
        customer_id: string | null;
        enforce_2fa?: (boolean | null) | undefined;
        enforce_verified_domains?: (boolean | null) | undefined;
        members_can_invite?: (boolean | null) | undefined;
        members_can_create_projects?: (boolean | null) | undefined;
        members_can_use_personal_api_keys?: boolean | undefined;
        members_can_see_org_members?: boolean | undefined;
        allow_publicly_shared_resources?: boolean | undefined;
        read_only_mcp_access?: (boolean | null) | undefined;
        member_count: number;
        is_ai_data_processing_approved?: (boolean | null) | undefined;
        is_ai_training_opted_in?: (boolean | null) | undefined;
        /**
         * When True, the AI training opt-out setting cannot be modified through the UI or API.
         */
        is_ai_training_locked: boolean | null;
        /**
         * When True, in-app callouts inviting members to enable AI training are shown.
         */
        is_ai_training_cta_shown: boolean | null;
        is_hipaa: boolean | null;
        default_experiment_stats_method?:
            | (
                  | OrganizationDefaultExperimentStatsMethodEnum
                  | BlankEnum
                  | NullEnum
              )
            | undefined;
        default_anonymize_ips?: boolean | undefined;
        default_role_id?: (string | null) | undefined;
        /**
         * Set this to 'No' to temporarily disable an organization.
         */
        is_active: boolean | null;
        /**
         * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
         */
        is_not_active_reason: string | null;
        /**
         * Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.
         */
        is_pending_deletion: boolean | null;
    };
    /**
     * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
     * Also used for nested serializers.
     */
    export type OrganizationBasic = {
        id: string;
        name: string;
        slug: string;
        logo_media_id: string | null;
        membership_level: OrganizationMembershipLevelEnum & unknown;
        /**
         * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
         * Also used for nested serializers.
         */
        members_can_use_personal_api_keys?: boolean | undefined;
        /**
         * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
         * Also used for nested serializers.
         */
        is_active?: (boolean | null) | undefined;
        /**
         * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
         * Also used for nested serializers.
         */
        is_not_active_reason?: (string | null) | undefined;
        /**
         * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
         * Also used for nested serializers.
         */
        is_pending_deletion?: (boolean | null) | undefined;
    };
    /**
     * * `discussions_mentioned` - discussions_mentioned
     * * `error_tracking_issue_assigned` - error_tracking_issue_assigned
     * * `error_tracking_weekly_digest_project_enabled` - error_tracking_weekly_digest_project_enabled
     * * `materialized_view_sync_failed` - materialized_view_sync_failed
     * * `materialized_view_sync_failed_daily` - materialized_view_sync_failed_daily
     * * `materialized_view_sync_failed_immediate` - materialized_view_sync_failed_immediate
     * * `organization_member_join_email_disabled` - organization_member_join_email_disabled
     * * `pipeline_notifications_disabled` - pipeline_notifications_disabled
     * * `project_weekly_digest_disabled` - project_weekly_digest_disabled
     * * `web_analytics_weekly_digest_project_enabled` - web_analytics_weekly_digest_project_enabled
     */
    export type SettingEnum =
        | "discussions_mentioned"
        | "error_tracking_issue_assigned"
        | "error_tracking_weekly_digest_project_enabled"
        | "materialized_view_sync_failed"
        | "materialized_view_sync_failed_daily"
        | "materialized_view_sync_failed_immediate"
        | "organization_member_join_email_disabled"
        | "pipeline_notifications_disabled"
        | "project_weekly_digest_disabled"
        | "web_analytics_weekly_digest_project_enabled";
    export type OrganizationNotificationLock = {
        /**
         * Notification setting this rule enforces.
         *
         * * `discussions_mentioned` - discussions_mentioned
         * * `error_tracking_issue_assigned` - error_tracking_issue_assigned
         * * `error_tracking_weekly_digest_project_enabled` - error_tracking_weekly_digest_project_enabled
         * * `materialized_view_sync_failed` - materialized_view_sync_failed
         * * `materialized_view_sync_failed_daily` - materialized_view_sync_failed_daily
         * * `materialized_view_sync_failed_immediate` - materialized_view_sync_failed_immediate
         * * `organization_member_join_email_disabled` - organization_member_join_email_disabled
         * * `pipeline_notifications_disabled` - pipeline_notifications_disabled
         * * `project_weekly_digest_disabled` - project_weekly_digest_disabled
         * * `web_analytics_weekly_digest_project_enabled` - web_analytics_weekly_digest_project_enabled
         */
        setting: SettingEnum;
        /**
         * What the setting applies to: a project ID or an organization ID. Empty for a setting that is a single switch.
         */
        scope_id: string;
        /**
         * The value the organization enforces.
         */
        locked_value: boolean;
    };
    export type PaginatedCommentList = {
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<Comment>;
    };
    export type PaginatedEvaluationList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<Evaluation>;
    };
    export type PaginatedExternalDataSchemaList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<ExternalDataSchema>;
    };
    export type PaginatedExternalDataSourceSerializersList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<ExternalDataSourceSerializers>;
    };
    export type PaginatedFeatureFlagList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<FeatureFlag>;
    };
    export type PaginatedHogFlowMinimalList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<HogFlowMinimal>;
    };
    export type PersonRecord = {
        /**
         * Numeric person ID.
         */
        id: number;
        /**
         * Display name derived from person properties (email, name, or username).
         */
        name: string;
        distinct_ids: Array<string>;
        properties?: unknown | undefined;
        /**
         * When this person was first seen (ISO 8601).
         */
        created_at: string;
        /**
         * Unique identifier (UUID) for this person.
         */
        uuid: string;
        /**
         * Timestamp of the last event from this person, or null.
         */
        last_seen_at: string | null;
    };
    export type PaginatedPersonRecordList = Partial<{
        next: string | null;
        previous: string | null;
        count: number;
        results: Array<PersonRecord>;
    }>;
    /**
     * * `acp` - ACP
     * * `pi` - Pi
     */
    export type TaskRuntimeEnum = "acp" | "pi";
    /**
     * * `claude` - claude
     * * `codex` - codex
     */
    export type RuntimeAdapterEnum = "claude" | "codex";
    /**
     * * `anthropic` - anthropic
     * * `openai` - openai
     */
    export type TaskRunDetailDTOProviderEnum = "anthropic" | "openai";
    /**
     * * `off` - off
     * * `minimal` - minimal
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode
     */
    export type TaskRunReasoningEffortEnum =
        | "off"
        | "minimal"
        | "low"
        | "medium"
        | "high"
        | "xhigh"
        | "max"
        | "ultracode";
    /**
     * * `user` - user
     * * `repo` - repo
     * * `marketplace` - marketplace
     * * `codex` - codex
     */
    export type SkillSourceEnum = "user" | "repo" | "marketplace" | "codex";
    export type TaskRunSkillBundleMetadata = {
        /**
         * Name of the local skill included in a skill_bundle artifact.
         */
        skill_name: string;
        /**
         * Local source for the uploaded skill bundle, such as user or repo.
         *
         * * `user` - user
         * * `repo` - repo
         * * `marketplace` - marketplace
         * * `codex` - codex
         */
        skill_source: SkillSourceEnum;
        /**
         * SHA-256 hex digest of the uploaded skill bundle bytes.
         */
        content_sha256: string;
        /**
         * Archive format used for the local skill bundle.
         *
         * * `zip` - zip
         */
        bundle_format: BundleFormatEnum;
        /**
         * Version of the local skill bundle metadata schema.
         */
        schema_version: number;
    };
    /**
     * * `posthog_object` - posthog_object
     */
    export type ReferenceTypeEnum = "posthog_object";
    export type TaskRunPostHogReferenceMetadata = {
        /**
         * Reference metadata type. posthog_object identifies a live PostHog object.
         *
         * * `posthog_object` - posthog_object
         */
        reference_type: ReferenceTypeEnum;
        /**
         * PostHog object kind used to resolve the reference.
         *
         * * `insight` - insight
         * * `hogql` - hogql
         * * `dashboard` - dashboard
         * * `error` - error
         * * `replay` - replay
         * * `flag` - flag
         * * `experiment` - experiment
         * * `survey` - survey
         * * `ticket` - ticket
         * * `trace` - trace
         * * `eval` - eval
         * * `event` - event
         * * `cohort` - cohort
         * * `action` - action
         * * `person` - person
         */
        object_kind: ObjectKindEnum;
        /**
         * Exact PostHog object identifier, flag key, event name, or SQL query.
         */
        object_id: string;
        /**
         * Completed assistant message identifiers that referenced the object.
         */
        source_message_ids: Array<string>;
        /**
         * Number of distinct completed assistant messages that referenced the object.
         */
        occurrence_count: number;
    };
    export type TaskRunArtifactMetadata =
        | TaskRunSkillBundleMetadata
        | TaskRunPostHogReferenceMetadata;
    /**
     * * `agent` - agent
     * * `user` - user
     */
    export type UploadedByEnum = "agent" | "user";
    export type TaskRunArtifactResponse = {
        id?: string | undefined;
        /**
         * Artifact file name
         */
        name: string;
        /**
         * Artifact classification (plan, context, etc.)
         */
        type: string;
        source?: string | undefined;
        size?: number | undefined;
        content_type?: string | undefined;
        metadata?: TaskRunArtifactMetadata | undefined;
        storage_path?: string | undefined;
        /**
         * Timestamp when the artifact was uploaded or registered
         */
        uploaded_at: string;
        uploaded_by?: UploadedByEnum | undefined;
        uploaded_by_user_id?: number | undefined;
        dismissed_at?: string | undefined;
        url?: string | undefined;
    };
    /**
     * Detail response for a task run.
     *
     * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
     * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
     * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
     * ``latest_run`` shape by the task detail response.
     */
    export type TaskRunDetailDTO = {
        id: string;
        /**
         * Parent task id this run belongs to.
         */
        task: string;
        stage: string | null;
        branch: string | null;
        status: string;
        environment: string;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        runtime_adapter?: (RuntimeAdapterEnum | NullEnum) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        provider?: (TaskRunDetailDTOProviderEnum | NullEnum) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        model?: (string | null) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        reasoning_effort?: (TaskRunReasoningEffortEnum | NullEnum) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        log_url?: (string | null) | undefined;
        error_message: string | null;
        output: Record<string, unknown> | null;
        state: Record<string, unknown>;
        artifacts: Array<TaskRunArtifactResponse>;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        created_at?: (string | null) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        updated_at?: (string | null) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        completed_at?: (string | null) | undefined;
        /**
         * Detail response for a task run.
         *
         * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
         * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
         * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
         * ``latest_run`` shape by the task detail response.
         */
        preview_available?: boolean | undefined;
    };
    /**
     * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
     */
    export type TaskUserBasicInfo = {
        id: number;
        uuid: string;
        distinct_id: string;
        first_name: string;
        last_name: string;
        email: string;
        /**
         * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
         */
        is_email_verified?: (boolean | null) | undefined;
        /**
         * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
         */
        hedgehog_config?: (Record<string, unknown> | null) | undefined;
        /**
         * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
         */
        role_at_organization?: (string | null) | undefined;
    };
    export type SlackThreadReferenceDTO = {
        url: string;
        channel: string;
        created_at?: (string | null) | undefined;
    };
    /**
     * Detail response for a task.
     *
     * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
     * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
     * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
     */
    export type TaskDetailDTO = {
        id: string;
        task_number: number | null;
        slug: string;
        title: string;
        title_manually_set: boolean;
        description: string;
        origin_product: string;
        /**
         * Agent protocol and harness used for this task's runs.
         *
         * * `acp` - ACP
         * * `pi` - Pi
         */
        runtime: TaskRuntimeEnum;
        repository: string | null;
        repositories: Array<string>;
        github_integration: number | null;
        github_user_integration: string | null;
        signal_report: string | null;
        json_schema: Record<string, unknown> | null;
        internal: boolean;
        archived: boolean;
        archived_at: string | null;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        latest_run?: (TaskRunDetailDTO | null) | undefined;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        created_at?: (string | null) | undefined;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        updated_at?: (string | null) | undefined;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        last_activity_at?: (string | null) | undefined;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        created_by?: (TaskUserBasicInfo | null) | undefined;
        ci_prompt: string | null;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        channel?: (string | null) | undefined;
        slack_thread_references: Array<SlackThreadReferenceDTO>;
        /**
         * Detail response for a task.
         *
         * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
         * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
         * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
         */
        origin_key?: (string | null) | undefined;
    };
    export type PaginatedTaskDetailDTOList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<TaskDetailDTO>;
    };
    export type PaginatedTaskRunDetailDTOList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<TaskRunDetailDTO>;
    };
    /**
     * * `not_started` - Not Started
     * * `queued` - Queued
     * * `in_progress` - In Progress
     * * `completed` - Completed
     * * `failed` - Failed
     * * `cancelled` - Cancelled
     */
    export type TaskRunStatusEnum =
        | "not_started"
        | "queued"
        | "in_progress"
        | "completed"
        | "failed"
        | "cancelled";
    /**
     * * `local` - Local
     * * `cloud` - Cloud
     */
    export type TaskRunEnvironmentEnum = "local" | "cloud";
    export type TaskRunSummary = {
        /**
         * ID of the latest run.
         */
        id: string;
        status: TaskRunStatusEnum | NullEnum;
        environment: TaskRunEnvironmentEnum | NullEnum;
    };
    /**
     * Summary response for a task — reads from a frozen ``TaskSummaryDTO``.
     */
    export type TaskSummaryDTO = {
        id: string;
        title: string;
        repository: string | null;
        /**
         * ID of the user who created the task, or null for system-created tasks.
         */
        created_by_id: number | null;
        created_at: string;
        updated_at: string;
        /**
         * Summary response for a task — reads from a frozen ``TaskSummaryDTO``.
         */
        origin_product?: string | undefined;
        /**
         * Summary response for a task — reads from a frozen ``TaskSummaryDTO``.
         */
        latest_run?: (TaskRunSummary | null) | undefined;
    };
    export type PaginatedTaskSummaryDTOList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<TaskSummaryDTO>;
    };
    /**
     * * `disabled` - disabled
     * * `toolbar` - toolbar
     */
    export type ToolbarModeEnum = "disabled" | "toolbar";
    /**
     * * `Africa/Abidjan` - Africa/Abidjan
     * * `Africa/Accra` - Africa/Accra
     * * `Africa/Addis_Ababa` - Africa/Addis_Ababa
     * * `Africa/Algiers` - Africa/Algiers
     * * `Africa/Asmara` - Africa/Asmara
     * * `Africa/Asmera` - Africa/Asmera
     * * `Africa/Bamako` - Africa/Bamako
     * * `Africa/Bangui` - Africa/Bangui
     * * `Africa/Banjul` - Africa/Banjul
     * * `Africa/Bissau` - Africa/Bissau
     * * `Africa/Blantyre` - Africa/Blantyre
     * * `Africa/Brazzaville` - Africa/Brazzaville
     * * `Africa/Bujumbura` - Africa/Bujumbura
     * * `Africa/Cairo` - Africa/Cairo
     * * `Africa/Casablanca` - Africa/Casablanca
     * * `Africa/Ceuta` - Africa/Ceuta
     * * `Africa/Conakry` - Africa/Conakry
     * * `Africa/Dakar` - Africa/Dakar
     * * `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam
     * * `Africa/Djibouti` - Africa/Djibouti
     * * `Africa/Douala` - Africa/Douala
     * * `Africa/El_Aaiun` - Africa/El_Aaiun
     * * `Africa/Freetown` - Africa/Freetown
     * * `Africa/Gaborone` - Africa/Gaborone
     * * `Africa/Harare` - Africa/Harare
     * * `Africa/Johannesburg` - Africa/Johannesburg
     * * `Africa/Juba` - Africa/Juba
     * * `Africa/Kampala` - Africa/Kampala
     * * `Africa/Khartoum` - Africa/Khartoum
     * * `Africa/Kigali` - Africa/Kigali
     * * `Africa/Kinshasa` - Africa/Kinshasa
     * * `Africa/Lagos` - Africa/Lagos
     * * `Africa/Libreville` - Africa/Libreville
     * * `Africa/Lome` - Africa/Lome
     * * `Africa/Luanda` - Africa/Luanda
     * * `Africa/Lubumbashi` - Africa/Lubumbashi
     * * `Africa/Lusaka` - Africa/Lusaka
     * * `Africa/Malabo` - Africa/Malabo
     * * `Africa/Maputo` - Africa/Maputo
     * * `Africa/Maseru` - Africa/Maseru
     * * `Africa/Mbabane` - Africa/Mbabane
     * * `Africa/Mogadishu` - Africa/Mogadishu
     * * `Africa/Monrovia` - Africa/Monrovia
     * * `Africa/Nairobi` - Africa/Nairobi
     * * `Africa/Ndjamena` - Africa/Ndjamena
     * * `Africa/Niamey` - Africa/Niamey
     * * `Africa/Nouakchott` - Africa/Nouakchott
     * * `Africa/Ouagadougou` - Africa/Ouagadougou
     * * `Africa/Porto-Novo` - Africa/Porto-Novo
     * * `Africa/Sao_Tome` - Africa/Sao_Tome
     * * `Africa/Timbuktu` - Africa/Timbuktu
     * * `Africa/Tripoli` - Africa/Tripoli
     * * `Africa/Tunis` - Africa/Tunis
     * * `Africa/Windhoek` - Africa/Windhoek
     * * `America/Adak` - America/Adak
     * * `America/Anchorage` - America/Anchorage
     * * `America/Anguilla` - America/Anguilla
     * * `America/Antigua` - America/Antigua
     * * `America/Araguaina` - America/Araguaina
     * * `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires
     * * `America/Argentina/Catamarca` - America/Argentina/Catamarca
     * * `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia
     * * `America/Argentina/Cordoba` - America/Argentina/Cordoba
     * * `America/Argentina/Jujuy` - America/Argentina/Jujuy
     * * `America/Argentina/La_Rioja` - America/Argentina/La_Rioja
     * * `America/Argentina/Mendoza` - America/Argentina/Mendoza
     * * `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos
     * * `America/Argentina/Salta` - America/Argentina/Salta
     * * `America/Argentina/San_Juan` - America/Argentina/San_Juan
     * * `America/Argentina/San_Luis` - America/Argentina/San_Luis
     * * `America/Argentina/Tucuman` - America/Argentina/Tucuman
     * * `America/Argentina/Ushuaia` - America/Argentina/Ushuaia
     * * `America/Aruba` - America/Aruba
     * * `America/Asuncion` - America/Asuncion
     * * `America/Atikokan` - America/Atikokan
     * * `America/Atka` - America/Atka
     * * `America/Bahia` - America/Bahia
     * * `America/Bahia_Banderas` - America/Bahia_Banderas
     * * `America/Barbados` - America/Barbados
     * * `America/Belem` - America/Belem
     * * `America/Belize` - America/Belize
     * * `America/Blanc-Sablon` - America/Blanc-Sablon
     * * `America/Boa_Vista` - America/Boa_Vista
     * * `America/Bogota` - America/Bogota
     * * `America/Boise` - America/Boise
     * * `America/Buenos_Aires` - America/Buenos_Aires
     * * `America/Cambridge_Bay` - America/Cambridge_Bay
     * * `America/Campo_Grande` - America/Campo_Grande
     * * `America/Cancun` - America/Cancun
     * * `America/Caracas` - America/Caracas
     * * `America/Catamarca` - America/Catamarca
     * * `America/Cayenne` - America/Cayenne
     * * `America/Cayman` - America/Cayman
     * * `America/Chicago` - America/Chicago
     * * `America/Chihuahua` - America/Chihuahua
     * * `America/Ciudad_Juarez` - America/Ciudad_Juarez
     * * `America/Coral_Harbour` - America/Coral_Harbour
     * * `America/Cordoba` - America/Cordoba
     * * `America/Costa_Rica` - America/Costa_Rica
     * * `America/Creston` - America/Creston
     * * `America/Cuiaba` - America/Cuiaba
     * * `America/Curacao` - America/Curacao
     * * `America/Danmarkshavn` - America/Danmarkshavn
     * * `America/Dawson` - America/Dawson
     * * `America/Dawson_Creek` - America/Dawson_Creek
     * * `America/Denver` - America/Denver
     * * `America/Detroit` - America/Detroit
     * * `America/Dominica` - America/Dominica
     * * `America/Edmonton` - America/Edmonton
     * * `America/Eirunepe` - America/Eirunepe
     * * `America/El_Salvador` - America/El_Salvador
     * * `America/Ensenada` - America/Ensenada
     * * `America/Fort_Nelson` - America/Fort_Nelson
     * * `America/Fort_Wayne` - America/Fort_Wayne
     * * `America/Fortaleza` - America/Fortaleza
     * * `America/Glace_Bay` - America/Glace_Bay
     * * `America/Godthab` - America/Godthab
     * * `America/Goose_Bay` - America/Goose_Bay
     * * `America/Grand_Turk` - America/Grand_Turk
     * * `America/Grenada` - America/Grenada
     * * `America/Guadeloupe` - America/Guadeloupe
     * * `America/Guatemala` - America/Guatemala
     * * `America/Guayaquil` - America/Guayaquil
     * * `America/Guyana` - America/Guyana
     * * `America/Halifax` - America/Halifax
     * * `America/Havana` - America/Havana
     * * `America/Hermosillo` - America/Hermosillo
     * * `America/Indiana/Indianapolis` - America/Indiana/Indianapolis
     * * `America/Indiana/Knox` - America/Indiana/Knox
     * * `America/Indiana/Marengo` - America/Indiana/Marengo
     * * `America/Indiana/Petersburg` - America/Indiana/Petersburg
     * * `America/Indiana/Tell_City` - America/Indiana/Tell_City
     * * `America/Indiana/Vevay` - America/Indiana/Vevay
     * * `America/Indiana/Vincennes` - America/Indiana/Vincennes
     * * `America/Indiana/Winamac` - America/Indiana/Winamac
     * * `America/Indianapolis` - America/Indianapolis
     * * `America/Inuvik` - America/Inuvik
     * * `America/Iqaluit` - America/Iqaluit
     * * `America/Jamaica` - America/Jamaica
     * * `America/Jujuy` - America/Jujuy
     * * `America/Juneau` - America/Juneau
     * * `America/Kentucky/Louisville` - America/Kentucky/Louisville
     * * `America/Kentucky/Monticello` - America/Kentucky/Monticello
     * * `America/Knox_IN` - America/Knox_IN
     * * `America/Kralendijk` - America/Kralendijk
     * * `America/La_Paz` - America/La_Paz
     * * `America/Lima` - America/Lima
     * * `America/Los_Angeles` - America/Los_Angeles
     * * `America/Louisville` - America/Louisville
     * * `America/Lower_Princes` - America/Lower_Princes
     * * `America/Maceio` - America/Maceio
     * * `America/Managua` - America/Managua
     * * `America/Manaus` - America/Manaus
     * * `America/Marigot` - America/Marigot
     * * `America/Martinique` - America/Martinique
     * * `America/Matamoros` - America/Matamoros
     * * `America/Mazatlan` - America/Mazatlan
     * * `America/Mendoza` - America/Mendoza
     * * `America/Menominee` - America/Menominee
     * * `America/Merida` - America/Merida
     * * `America/Metlakatla` - America/Metlakatla
     * * `America/Mexico_City` - America/Mexico_City
     * * `America/Miquelon` - America/Miquelon
     * * `America/Moncton` - America/Moncton
     * * `America/Monterrey` - America/Monterrey
     * * `America/Montevideo` - America/Montevideo
     * * `America/Montreal` - America/Montreal
     * * `America/Montserrat` - America/Montserrat
     * * `America/Nassau` - America/Nassau
     * * `America/New_York` - America/New_York
     * * `America/Nipigon` - America/Nipigon
     * * `America/Nome` - America/Nome
     * * `America/Noronha` - America/Noronha
     * * `America/North_Dakota/Beulah` - America/North_Dakota/Beulah
     * * `America/North_Dakota/Center` - America/North_Dakota/Center
     * * `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem
     * * `America/Nuuk` - America/Nuuk
     * * `America/Ojinaga` - America/Ojinaga
     * * `America/Panama` - America/Panama
     * * `America/Pangnirtung` - America/Pangnirtung
     * * `America/Paramaribo` - America/Paramaribo
     * * `America/Phoenix` - America/Phoenix
     * * `America/Port-au-Prince` - America/Port-au-Prince
     * * `America/Port_of_Spain` - America/Port_of_Spain
     * * `America/Porto_Acre` - America/Porto_Acre
     * * `America/Porto_Velho` - America/Porto_Velho
     * * `America/Puerto_Rico` - America/Puerto_Rico
     * * `America/Punta_Arenas` - America/Punta_Arenas
     * * `America/Rainy_River` - America/Rainy_River
     * * `America/Rankin_Inlet` - America/Rankin_Inlet
     * * `America/Recife` - America/Recife
     * * `America/Regina` - America/Regina
     * * `America/Resolute` - America/Resolute
     * * `America/Rio_Branco` - America/Rio_Branco
     * * `America/Rosario` - America/Rosario
     * * `America/Santa_Isabel` - America/Santa_Isabel
     * * `America/Santarem` - America/Santarem
     * * `America/Santiago` - America/Santiago
     * * `America/Santo_Domingo` - America/Santo_Domingo
     * * `America/Sao_Paulo` - America/Sao_Paulo
     * * `America/Scoresbysund` - America/Scoresbysund
     * * `America/Shiprock` - America/Shiprock
     * * `America/Sitka` - America/Sitka
     * * `America/St_Barthelemy` - America/St_Barthelemy
     * * `America/St_Johns` - America/St_Johns
     * * `America/St_Kitts` - America/St_Kitts
     * * `America/St_Lucia` - America/St_Lucia
     * * `America/St_Thomas` - America/St_Thomas
     * * `America/St_Vincent` - America/St_Vincent
     * * `America/Swift_Current` - America/Swift_Current
     * * `America/Tegucigalpa` - America/Tegucigalpa
     * * `America/Thule` - America/Thule
     * * `America/Thunder_Bay` - America/Thunder_Bay
     * * `America/Tijuana` - America/Tijuana
     * * `America/Toronto` - America/Toronto
     * * `America/Tortola` - America/Tortola
     * * `America/Vancouver` - America/Vancouver
     * * `America/Virgin` - America/Virgin
     * * `America/Whitehorse` - America/Whitehorse
     * * `America/Winnipeg` - America/Winnipeg
     * * `America/Yakutat` - America/Yakutat
     * * `America/Yellowknife` - America/Yellowknife
     * * `Antarctica/Casey` - Antarctica/Casey
     * * `Antarctica/Davis` - Antarctica/Davis
     * * `Antarctica/DumontDUrville` - Antarctica/DumontDUrville
     * * `Antarctica/Macquarie` - Antarctica/Macquarie
     * * `Antarctica/Mawson` - Antarctica/Mawson
     * * `Antarctica/McMurdo` - Antarctica/McMurdo
     * * `Antarctica/Palmer` - Antarctica/Palmer
     * * `Antarctica/Rothera` - Antarctica/Rothera
     * * `Antarctica/South_Pole` - Antarctica/South_Pole
     * * `Antarctica/Syowa` - Antarctica/Syowa
     * * `Antarctica/Troll` - Antarctica/Troll
     * * `Antarctica/Vostok` - Antarctica/Vostok
     * * `Arctic/Longyearbyen` - Arctic/Longyearbyen
     * * `Asia/Aden` - Asia/Aden
     * * `Asia/Almaty` - Asia/Almaty
     * * `Asia/Amman` - Asia/Amman
     * * `Asia/Anadyr` - Asia/Anadyr
     * * `Asia/Aqtau` - Asia/Aqtau
     * * `Asia/Aqtobe` - Asia/Aqtobe
     * * `Asia/Ashgabat` - Asia/Ashgabat
     * * `Asia/Ashkhabad` - Asia/Ashkhabad
     * * `Asia/Atyrau` - Asia/Atyrau
     * * `Asia/Baghdad` - Asia/Baghdad
     * * `Asia/Bahrain` - Asia/Bahrain
     * * `Asia/Baku` - Asia/Baku
     * * `Asia/Bangkok` - Asia/Bangkok
     * * `Asia/Barnaul` - Asia/Barnaul
     * * `Asia/Beirut` - Asia/Beirut
     * * `Asia/Bishkek` - Asia/Bishkek
     * * `Asia/Brunei` - Asia/Brunei
     * * `Asia/Calcutta` - Asia/Calcutta
     * * `Asia/Chita` - Asia/Chita
     * * `Asia/Choibalsan` - Asia/Choibalsan
     * * `Asia/Chongqing` - Asia/Chongqing
     * * `Asia/Chungking` - Asia/Chungking
     * * `Asia/Colombo` - Asia/Colombo
     * * `Asia/Dacca` - Asia/Dacca
     * * `Asia/Damascus` - Asia/Damascus
     * * `Asia/Dhaka` - Asia/Dhaka
     * * `Asia/Dili` - Asia/Dili
     * * `Asia/Dubai` - Asia/Dubai
     * * `Asia/Dushanbe` - Asia/Dushanbe
     * * `Asia/Famagusta` - Asia/Famagusta
     * * `Asia/Gaza` - Asia/Gaza
     * * `Asia/Harbin` - Asia/Harbin
     * * `Asia/Hebron` - Asia/Hebron
     * * `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh
     * * `Asia/Hong_Kong` - Asia/Hong_Kong
     * * `Asia/Hovd` - Asia/Hovd
     * * `Asia/Irkutsk` - Asia/Irkutsk
     * * `Asia/Istanbul` - Asia/Istanbul
     * * `Asia/Jakarta` - Asia/Jakarta
     * * `Asia/Jayapura` - Asia/Jayapura
     * * `Asia/Jerusalem` - Asia/Jerusalem
     * * `Asia/Kabul` - Asia/Kabul
     * * `Asia/Kamchatka` - Asia/Kamchatka
     * * `Asia/Karachi` - Asia/Karachi
     * * `Asia/Kashgar` - Asia/Kashgar
     * * `Asia/Kathmandu` - Asia/Kathmandu
     * * `Asia/Katmandu` - Asia/Katmandu
     * * `Asia/Khandyga` - Asia/Khandyga
     * * `Asia/Kolkata` - Asia/Kolkata
     * * `Asia/Krasnoyarsk` - Asia/Krasnoyarsk
     * * `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur
     * * `Asia/Kuching` - Asia/Kuching
     * * `Asia/Kuwait` - Asia/Kuwait
     * * `Asia/Macao` - Asia/Macao
     * * `Asia/Macau` - Asia/Macau
     * * `Asia/Magadan` - Asia/Magadan
     * * `Asia/Makassar` - Asia/Makassar
     * * `Asia/Manila` - Asia/Manila
     * * `Asia/Muscat` - Asia/Muscat
     * * `Asia/Nicosia` - Asia/Nicosia
     * * `Asia/Novokuznetsk` - Asia/Novokuznetsk
     * * `Asia/Novosibirsk` - Asia/Novosibirsk
     * * `Asia/Omsk` - Asia/Omsk
     * * `Asia/Oral` - Asia/Oral
     * * `Asia/Phnom_Penh` - Asia/Phnom_Penh
     * * `Asia/Pontianak` - Asia/Pontianak
     * * `Asia/Pyongyang` - Asia/Pyongyang
     * * `Asia/Qatar` - Asia/Qatar
     * * `Asia/Qostanay` - Asia/Qostanay
     * * `Asia/Qyzylorda` - Asia/Qyzylorda
     * * `Asia/Rangoon` - Asia/Rangoon
     * * `Asia/Riyadh` - Asia/Riyadh
     * * `Asia/Saigon` - Asia/Saigon
     * * `Asia/Sakhalin` - Asia/Sakhalin
     * * `Asia/Samarkand` - Asia/Samarkand
     * * `Asia/Seoul` - Asia/Seoul
     * * `Asia/Shanghai` - Asia/Shanghai
     * * `Asia/Singapore` - Asia/Singapore
     * * `Asia/Srednekolymsk` - Asia/Srednekolymsk
     * * `Asia/Taipei` - Asia/Taipei
     * * `Asia/Tashkent` - Asia/Tashkent
     * * `Asia/Tbilisi` - Asia/Tbilisi
     * * `Asia/Tehran` - Asia/Tehran
     * * `Asia/Tel_Aviv` - Asia/Tel_Aviv
     * * `Asia/Thimbu` - Asia/Thimbu
     * * `Asia/Thimphu` - Asia/Thimphu
     * * `Asia/Tokyo` - Asia/Tokyo
     * * `Asia/Tomsk` - Asia/Tomsk
     * * `Asia/Ujung_Pandang` - Asia/Ujung_Pandang
     * * `Asia/Ulaanbaatar` - Asia/Ulaanbaatar
     * * `Asia/Ulan_Bator` - Asia/Ulan_Bator
     * * `Asia/Urumqi` - Asia/Urumqi
     * * `Asia/Ust-Nera` - Asia/Ust-Nera
     * * `Asia/Vientiane` - Asia/Vientiane
     * * `Asia/Vladivostok` - Asia/Vladivostok
     * * `Asia/Yakutsk` - Asia/Yakutsk
     * * `Asia/Yangon` - Asia/Yangon
     * * `Asia/Yekaterinburg` - Asia/Yekaterinburg
     * * `Asia/Yerevan` - Asia/Yerevan
     * * `Atlantic/Azores` - Atlantic/Azores
     * * `Atlantic/Bermuda` - Atlantic/Bermuda
     * * `Atlantic/Canary` - Atlantic/Canary
     * * `Atlantic/Cape_Verde` - Atlantic/Cape_Verde
     * * `Atlantic/Faeroe` - Atlantic/Faeroe
     * * `Atlantic/Faroe` - Atlantic/Faroe
     * * `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen
     * * `Atlantic/Madeira` - Atlantic/Madeira
     * * `Atlantic/Reykjavik` - Atlantic/Reykjavik
     * * `Atlantic/South_Georgia` - Atlantic/South_Georgia
     * * `Atlantic/St_Helena` - Atlantic/St_Helena
     * * `Atlantic/Stanley` - Atlantic/Stanley
     * * `Australia/ACT` - Australia/ACT
     * * `Australia/Adelaide` - Australia/Adelaide
     * * `Australia/Brisbane` - Australia/Brisbane
     * * `Australia/Broken_Hill` - Australia/Broken_Hill
     * * `Australia/Canberra` - Australia/Canberra
     * * `Australia/Currie` - Australia/Currie
     * * `Australia/Darwin` - Australia/Darwin
     * * `Australia/Eucla` - Australia/Eucla
     * * `Australia/Hobart` - Australia/Hobart
     * * `Australia/LHI` - Australia/LHI
     * * `Australia/Lindeman` - Australia/Lindeman
     * * `Australia/Lord_Howe` - Australia/Lord_Howe
     * * `Australia/Melbourne` - Australia/Melbourne
     * * `Australia/NSW` - Australia/NSW
     * * `Australia/North` - Australia/North
     * * `Australia/Perth` - Australia/Perth
     * * `Australia/Queensland` - Australia/Queensland
     * * `Australia/South` - Australia/South
     * * `Australia/Sydney` - Australia/Sydney
     * * `Australia/Tasmania` - Australia/Tasmania
     * * `Australia/Victoria` - Australia/Victoria
     * * `Australia/West` - Australia/West
     * * `Australia/Yancowinna` - Australia/Yancowinna
     * * `Brazil/Acre` - Brazil/Acre
     * * `Brazil/DeNoronha` - Brazil/DeNoronha
     * * `Brazil/East` - Brazil/East
     * * `Brazil/West` - Brazil/West
     * * `CET` - CET
     * * `CST6CDT` - CST6CDT
     * * `Canada/Atlantic` - Canada/Atlantic
     * * `Canada/Central` - Canada/Central
     * * `Canada/Eastern` - Canada/Eastern
     * * `Canada/Mountain` - Canada/Mountain
     * * `Canada/Newfoundland` - Canada/Newfoundland
     * * `Canada/Pacific` - Canada/Pacific
     * * `Canada/Saskatchewan` - Canada/Saskatchewan
     * * `Canada/Yukon` - Canada/Yukon
     * * `Chile/Continental` - Chile/Continental
     * * `Chile/EasterIsland` - Chile/EasterIsland
     * * `Cuba` - Cuba
     * * `EET` - EET
     * * `EST` - EST
     * * `EST5EDT` - EST5EDT
     * * `Egypt` - Egypt
     * * `Eire` - Eire
     * * `Etc/GMT` - Etc/GMT
     * * `Etc/GMT+0` - Etc/GMT+0
     * * `Etc/GMT+1` - Etc/GMT+1
     * * `Etc/GMT+10` - Etc/GMT+10
     * * `Etc/GMT+11` - Etc/GMT+11
     * * `Etc/GMT+12` - Etc/GMT+12
     * * `Etc/GMT+2` - Etc/GMT+2
     * * `Etc/GMT+3` - Etc/GMT+3
     * * `Etc/GMT+4` - Etc/GMT+4
     * * `Etc/GMT+5` - Etc/GMT+5
     * * `Etc/GMT+6` - Etc/GMT+6
     * * `Etc/GMT+7` - Etc/GMT+7
     * * `Etc/GMT+8` - Etc/GMT+8
     * * `Etc/GMT+9` - Etc/GMT+9
     * * `Etc/GMT-0` - Etc/GMT-0
     * * `Etc/GMT-1` - Etc/GMT-1
     * * `Etc/GMT-10` - Etc/GMT-10
     * * `Etc/GMT-11` - Etc/GMT-11
     * * `Etc/GMT-12` - Etc/GMT-12
     * * `Etc/GMT-13` - Etc/GMT-13
     * * `Etc/GMT-14` - Etc/GMT-14
     * * `Etc/GMT-2` - Etc/GMT-2
     * * `Etc/GMT-3` - Etc/GMT-3
     * * `Etc/GMT-4` - Etc/GMT-4
     * * `Etc/GMT-5` - Etc/GMT-5
     * * `Etc/GMT-6` - Etc/GMT-6
     * * `Etc/GMT-7` - Etc/GMT-7
     * * `Etc/GMT-8` - Etc/GMT-8
     * * `Etc/GMT-9` - Etc/GMT-9
     * * `Etc/GMT0` - Etc/GMT0
     * * `Etc/Greenwich` - Etc/Greenwich
     * * `Etc/UCT` - Etc/UCT
     * * `Etc/UTC` - Etc/UTC
     * * `Etc/Universal` - Etc/Universal
     * * `Etc/Zulu` - Etc/Zulu
     * * `Europe/Amsterdam` - Europe/Amsterdam
     * * `Europe/Andorra` - Europe/Andorra
     * * `Europe/Astrakhan` - Europe/Astrakhan
     * * `Europe/Athens` - Europe/Athens
     * * `Europe/Belfast` - Europe/Belfast
     * * `Europe/Belgrade` - Europe/Belgrade
     * * `Europe/Berlin` - Europe/Berlin
     * * `Europe/Bratislava` - Europe/Bratislava
     * * `Europe/Brussels` - Europe/Brussels
     * * `Europe/Bucharest` - Europe/Bucharest
     * * `Europe/Budapest` - Europe/Budapest
     * * `Europe/Busingen` - Europe/Busingen
     * * `Europe/Chisinau` - Europe/Chisinau
     * * `Europe/Copenhagen` - Europe/Copenhagen
     * * `Europe/Dublin` - Europe/Dublin
     * * `Europe/Gibraltar` - Europe/Gibraltar
     * * `Europe/Guernsey` - Europe/Guernsey
     * * `Europe/Helsinki` - Europe/Helsinki
     * * `Europe/Isle_of_Man` - Europe/Isle_of_Man
     * * `Europe/Istanbul` - Europe/Istanbul
     * * `Europe/Jersey` - Europe/Jersey
     * * `Europe/Kaliningrad` - Europe/Kaliningrad
     * * `Europe/Kiev` - Europe/Kiev
     * * `Europe/Kirov` - Europe/Kirov
     * * `Europe/Kyiv` - Europe/Kyiv
     * * `Europe/Lisbon` - Europe/Lisbon
     * * `Europe/Ljubljana` - Europe/Ljubljana
     * * `Europe/London` - Europe/London
     * * `Europe/Luxembourg` - Europe/Luxembourg
     * * `Europe/Madrid` - Europe/Madrid
     * * `Europe/Malta` - Europe/Malta
     * * `Europe/Mariehamn` - Europe/Mariehamn
     * * `Europe/Minsk` - Europe/Minsk
     * * `Europe/Monaco` - Europe/Monaco
     * * `Europe/Moscow` - Europe/Moscow
     * * `Europe/Nicosia` - Europe/Nicosia
     * * `Europe/Oslo` - Europe/Oslo
     * * `Europe/Paris` - Europe/Paris
     * * `Europe/Podgorica` - Europe/Podgorica
     * * `Europe/Prague` - Europe/Prague
     * * `Europe/Riga` - Europe/Riga
     * * `Europe/Rome` - Europe/Rome
     * * `Europe/Samara` - Europe/Samara
     * * `Europe/San_Marino` - Europe/San_Marino
     * * `Europe/Sarajevo` - Europe/Sarajevo
     * * `Europe/Saratov` - Europe/Saratov
     * * `Europe/Simferopol` - Europe/Simferopol
     * * `Europe/Skopje` - Europe/Skopje
     * * `Europe/Sofia` - Europe/Sofia
     * * `Europe/Stockholm` - Europe/Stockholm
     * * `Europe/Tallinn` - Europe/Tallinn
     * * `Europe/Tirane` - Europe/Tirane
     * * `Europe/Tiraspol` - Europe/Tiraspol
     * * `Europe/Ulyanovsk` - Europe/Ulyanovsk
     * * `Europe/Uzhgorod` - Europe/Uzhgorod
     * * `Europe/Vaduz` - Europe/Vaduz
     * * `Europe/Vatican` - Europe/Vatican
     * * `Europe/Vienna` - Europe/Vienna
     * * `Europe/Vilnius` - Europe/Vilnius
     * * `Europe/Volgograd` - Europe/Volgograd
     * * `Europe/Warsaw` - Europe/Warsaw
     * * `Europe/Zagreb` - Europe/Zagreb
     * * `Europe/Zaporozhye` - Europe/Zaporozhye
     * * `Europe/Zurich` - Europe/Zurich
     * * `GB` - GB
     * * `GB-Eire` - GB-Eire
     * * `GMT` - GMT
     * * `GMT+0` - GMT+0
     * * `GMT-0` - GMT-0
     * * `GMT0` - GMT0
     * * `Greenwich` - Greenwich
     * * `HST` - HST
     * * `Hongkong` - Hongkong
     * * `Iceland` - Iceland
     * * `Indian/Antananarivo` - Indian/Antananarivo
     * * `Indian/Chagos` - Indian/Chagos
     * * `Indian/Christmas` - Indian/Christmas
     * * `Indian/Cocos` - Indian/Cocos
     * * `Indian/Comoro` - Indian/Comoro
     * * `Indian/Kerguelen` - Indian/Kerguelen
     * * `Indian/Mahe` - Indian/Mahe
     * * `Indian/Maldives` - Indian/Maldives
     * * `Indian/Mauritius` - Indian/Mauritius
     * * `Indian/Mayotte` - Indian/Mayotte
     * * `Indian/Reunion` - Indian/Reunion
     * * `Iran` - Iran
     * * `Israel` - Israel
     * * `Jamaica` - Jamaica
     * * `Japan` - Japan
     * * `Kwajalein` - Kwajalein
     * * `Libya` - Libya
     * * `MET` - MET
     * * `MST` - MST
     * * `MST7MDT` - MST7MDT
     * * `Mexico/BajaNorte` - Mexico/BajaNorte
     * * `Mexico/BajaSur` - Mexico/BajaSur
     * * `Mexico/General` - Mexico/General
     * * `NZ` - NZ
     * * `NZ-CHAT` - NZ-CHAT
     * * `Navajo` - Navajo
     * * `PRC` - PRC
     * * `PST8PDT` - PST8PDT
     * * `Pacific/Apia` - Pacific/Apia
     * * `Pacific/Auckland` - Pacific/Auckland
     * * `Pacific/Bougainville` - Pacific/Bougainville
     * * `Pacific/Chatham` - Pacific/Chatham
     * * `Pacific/Chuuk` - Pacific/Chuuk
     * * `Pacific/Easter` - Pacific/Easter
     * * `Pacific/Efate` - Pacific/Efate
     * * `Pacific/Enderbury` - Pacific/Enderbury
     * * `Pacific/Fakaofo` - Pacific/Fakaofo
     * * `Pacific/Fiji` - Pacific/Fiji
     * * `Pacific/Funafuti` - Pacific/Funafuti
     * * `Pacific/Galapagos` - Pacific/Galapagos
     * * `Pacific/Gambier` - Pacific/Gambier
     * * `Pacific/Guadalcanal` - Pacific/Guadalcanal
     * * `Pacific/Guam` - Pacific/Guam
     * * `Pacific/Honolulu` - Pacific/Honolulu
     * * `Pacific/Johnston` - Pacific/Johnston
     * * `Pacific/Kanton` - Pacific/Kanton
     * * `Pacific/Kiritimati` - Pacific/Kiritimati
     * * `Pacific/Kosrae` - Pacific/Kosrae
     * * `Pacific/Kwajalein` - Pacific/Kwajalein
     * * `Pacific/Majuro` - Pacific/Majuro
     * * `Pacific/Marquesas` - Pacific/Marquesas
     * * `Pacific/Midway` - Pacific/Midway
     * * `Pacific/Nauru` - Pacific/Nauru
     * * `Pacific/Niue` - Pacific/Niue
     * * `Pacific/Norfolk` - Pacific/Norfolk
     * * `Pacific/Noumea` - Pacific/Noumea
     * * `Pacific/Pago_Pago` - Pacific/Pago_Pago
     * * `Pacific/Palau` - Pacific/Palau
     * * `Pacific/Pitcairn` - Pacific/Pitcairn
     * * `Pacific/Pohnpei` - Pacific/Pohnpei
     * * `Pacific/Ponape` - Pacific/Ponape
     * * `Pacific/Port_Moresby` - Pacific/Port_Moresby
     * * `Pacific/Rarotonga` - Pacific/Rarotonga
     * * `Pacific/Saipan` - Pacific/Saipan
     * * `Pacific/Samoa` - Pacific/Samoa
     * * `Pacific/Tahiti` - Pacific/Tahiti
     * * `Pacific/Tarawa` - Pacific/Tarawa
     * * `Pacific/Tongatapu` - Pacific/Tongatapu
     * * `Pacific/Truk` - Pacific/Truk
     * * `Pacific/Wake` - Pacific/Wake
     * * `Pacific/Wallis` - Pacific/Wallis
     * * `Pacific/Yap` - Pacific/Yap
     * * `Poland` - Poland
     * * `Portugal` - Portugal
     * * `ROC` - ROC
     * * `ROK` - ROK
     * * `Singapore` - Singapore
     * * `Turkey` - Turkey
     * * `UCT` - UCT
     * * `US/Alaska` - US/Alaska
     * * `US/Aleutian` - US/Aleutian
     * * `US/Arizona` - US/Arizona
     * * `US/Central` - US/Central
     * * `US/East-Indiana` - US/East-Indiana
     * * `US/Eastern` - US/Eastern
     * * `US/Hawaii` - US/Hawaii
     * * `US/Indiana-Starke` - US/Indiana-Starke
     * * `US/Michigan` - US/Michigan
     * * `US/Mountain` - US/Mountain
     * * `US/Pacific` - US/Pacific
     * * `US/Samoa` - US/Samoa
     * * `UTC` - UTC
     * * `Universal` - Universal
     * * `W-SU` - W-SU
     * * `WET` - WET
     * * `Zulu` - Zulu
     */
    export type TimezoneEnum =
        | "Africa/Abidjan"
        | "Africa/Accra"
        | "Africa/Addis_Ababa"
        | "Africa/Algiers"
        | "Africa/Asmara"
        | "Africa/Asmera"
        | "Africa/Bamako"
        | "Africa/Bangui"
        | "Africa/Banjul"
        | "Africa/Bissau"
        | "Africa/Blantyre"
        | "Africa/Brazzaville"
        | "Africa/Bujumbura"
        | "Africa/Cairo"
        | "Africa/Casablanca"
        | "Africa/Ceuta"
        | "Africa/Conakry"
        | "Africa/Dakar"
        | "Africa/Dar_es_Salaam"
        | "Africa/Djibouti"
        | "Africa/Douala"
        | "Africa/El_Aaiun"
        | "Africa/Freetown"
        | "Africa/Gaborone"
        | "Africa/Harare"
        | "Africa/Johannesburg"
        | "Africa/Juba"
        | "Africa/Kampala"
        | "Africa/Khartoum"
        | "Africa/Kigali"
        | "Africa/Kinshasa"
        | "Africa/Lagos"
        | "Africa/Libreville"
        | "Africa/Lome"
        | "Africa/Luanda"
        | "Africa/Lubumbashi"
        | "Africa/Lusaka"
        | "Africa/Malabo"
        | "Africa/Maputo"
        | "Africa/Maseru"
        | "Africa/Mbabane"
        | "Africa/Mogadishu"
        | "Africa/Monrovia"
        | "Africa/Nairobi"
        | "Africa/Ndjamena"
        | "Africa/Niamey"
        | "Africa/Nouakchott"
        | "Africa/Ouagadougou"
        | "Africa/Porto-Novo"
        | "Africa/Sao_Tome"
        | "Africa/Timbuktu"
        | "Africa/Tripoli"
        | "Africa/Tunis"
        | "Africa/Windhoek"
        | "America/Adak"
        | "America/Anchorage"
        | "America/Anguilla"
        | "America/Antigua"
        | "America/Araguaina"
        | "America/Argentina/Buenos_Aires"
        | "America/Argentina/Catamarca"
        | "America/Argentina/ComodRivadavia"
        | "America/Argentina/Cordoba"
        | "America/Argentina/Jujuy"
        | "America/Argentina/La_Rioja"
        | "America/Argentina/Mendoza"
        | "America/Argentina/Rio_Gallegos"
        | "America/Argentina/Salta"
        | "America/Argentina/San_Juan"
        | "America/Argentina/San_Luis"
        | "America/Argentina/Tucuman"
        | "America/Argentina/Ushuaia"
        | "America/Aruba"
        | "America/Asuncion"
        | "America/Atikokan"
        | "America/Atka"
        | "America/Bahia"
        | "America/Bahia_Banderas"
        | "America/Barbados"
        | "America/Belem"
        | "America/Belize"
        | "America/Blanc-Sablon"
        | "America/Boa_Vista"
        | "America/Bogota"
        | "America/Boise"
        | "America/Buenos_Aires"
        | "America/Cambridge_Bay"
        | "America/Campo_Grande"
        | "America/Cancun"
        | "America/Caracas"
        | "America/Catamarca"
        | "America/Cayenne"
        | "America/Cayman"
        | "America/Chicago"
        | "America/Chihuahua"
        | "America/Ciudad_Juarez"
        | "America/Coral_Harbour"
        | "America/Cordoba"
        | "America/Costa_Rica"
        | "America/Creston"
        | "America/Cuiaba"
        | "America/Curacao"
        | "America/Danmarkshavn"
        | "America/Dawson"
        | "America/Dawson_Creek"
        | "America/Denver"
        | "America/Detroit"
        | "America/Dominica"
        | "America/Edmonton"
        | "America/Eirunepe"
        | "America/El_Salvador"
        | "America/Ensenada"
        | "America/Fort_Nelson"
        | "America/Fort_Wayne"
        | "America/Fortaleza"
        | "America/Glace_Bay"
        | "America/Godthab"
        | "America/Goose_Bay"
        | "America/Grand_Turk"
        | "America/Grenada"
        | "America/Guadeloupe"
        | "America/Guatemala"
        | "America/Guayaquil"
        | "America/Guyana"
        | "America/Halifax"
        | "America/Havana"
        | "America/Hermosillo"
        | "America/Indiana/Indianapolis"
        | "America/Indiana/Knox"
        | "America/Indiana/Marengo"
        | "America/Indiana/Petersburg"
        | "America/Indiana/Tell_City"
        | "America/Indiana/Vevay"
        | "America/Indiana/Vincennes"
        | "America/Indiana/Winamac"
        | "America/Indianapolis"
        | "America/Inuvik"
        | "America/Iqaluit"
        | "America/Jamaica"
        | "America/Jujuy"
        | "America/Juneau"
        | "America/Kentucky/Louisville"
        | "America/Kentucky/Monticello"
        | "America/Knox_IN"
        | "America/Kralendijk"
        | "America/La_Paz"
        | "America/Lima"
        | "America/Los_Angeles"
        | "America/Louisville"
        | "America/Lower_Princes"
        | "America/Maceio"
        | "America/Managua"
        | "America/Manaus"
        | "America/Marigot"
        | "America/Martinique"
        | "America/Matamoros"
        | "America/Mazatlan"
        | "America/Mendoza"
        | "America/Menominee"
        | "America/Merida"
        | "America/Metlakatla"
        | "America/Mexico_City"
        | "America/Miquelon"
        | "America/Moncton"
        | "America/Monterrey"
        | "America/Montevideo"
        | "America/Montreal"
        | "America/Montserrat"
        | "America/Nassau"
        | "America/New_York"
        | "America/Nipigon"
        | "America/Nome"
        | "America/Noronha"
        | "America/North_Dakota/Beulah"
        | "America/North_Dakota/Center"
        | "America/North_Dakota/New_Salem"
        | "America/Nuuk"
        | "America/Ojinaga"
        | "America/Panama"
        | "America/Pangnirtung"
        | "America/Paramaribo"
        | "America/Phoenix"
        | "America/Port-au-Prince"
        | "America/Port_of_Spain"
        | "America/Porto_Acre"
        | "America/Porto_Velho"
        | "America/Puerto_Rico"
        | "America/Punta_Arenas"
        | "America/Rainy_River"
        | "America/Rankin_Inlet"
        | "America/Recife"
        | "America/Regina"
        | "America/Resolute"
        | "America/Rio_Branco"
        | "America/Rosario"
        | "America/Santa_Isabel"
        | "America/Santarem"
        | "America/Santiago"
        | "America/Santo_Domingo"
        | "America/Sao_Paulo"
        | "America/Scoresbysund"
        | "America/Shiprock"
        | "America/Sitka"
        | "America/St_Barthelemy"
        | "America/St_Johns"
        | "America/St_Kitts"
        | "America/St_Lucia"
        | "America/St_Thomas"
        | "America/St_Vincent"
        | "America/Swift_Current"
        | "America/Tegucigalpa"
        | "America/Thule"
        | "America/Thunder_Bay"
        | "America/Tijuana"
        | "America/Toronto"
        | "America/Tortola"
        | "America/Vancouver"
        | "America/Virgin"
        | "America/Whitehorse"
        | "America/Winnipeg"
        | "America/Yakutat"
        | "America/Yellowknife"
        | "Antarctica/Casey"
        | "Antarctica/Davis"
        | "Antarctica/DumontDUrville"
        | "Antarctica/Macquarie"
        | "Antarctica/Mawson"
        | "Antarctica/McMurdo"
        | "Antarctica/Palmer"
        | "Antarctica/Rothera"
        | "Antarctica/South_Pole"
        | "Antarctica/Syowa"
        | "Antarctica/Troll"
        | "Antarctica/Vostok"
        | "Arctic/Longyearbyen"
        | "Asia/Aden"
        | "Asia/Almaty"
        | "Asia/Amman"
        | "Asia/Anadyr"
        | "Asia/Aqtau"
        | "Asia/Aqtobe"
        | "Asia/Ashgabat"
        | "Asia/Ashkhabad"
        | "Asia/Atyrau"
        | "Asia/Baghdad"
        | "Asia/Bahrain"
        | "Asia/Baku"
        | "Asia/Bangkok"
        | "Asia/Barnaul"
        | "Asia/Beirut"
        | "Asia/Bishkek"
        | "Asia/Brunei"
        | "Asia/Calcutta"
        | "Asia/Chita"
        | "Asia/Choibalsan"
        | "Asia/Chongqing"
        | "Asia/Chungking"
        | "Asia/Colombo"
        | "Asia/Dacca"
        | "Asia/Damascus"
        | "Asia/Dhaka"
        | "Asia/Dili"
        | "Asia/Dubai"
        | "Asia/Dushanbe"
        | "Asia/Famagusta"
        | "Asia/Gaza"
        | "Asia/Harbin"
        | "Asia/Hebron"
        | "Asia/Ho_Chi_Minh"
        | "Asia/Hong_Kong"
        | "Asia/Hovd"
        | "Asia/Irkutsk"
        | "Asia/Istanbul"
        | "Asia/Jakarta"
        | "Asia/Jayapura"
        | "Asia/Jerusalem"
        | "Asia/Kabul"
        | "Asia/Kamchatka"
        | "Asia/Karachi"
        | "Asia/Kashgar"
        | "Asia/Kathmandu"
        | "Asia/Katmandu"
        | "Asia/Khandyga"
        | "Asia/Kolkata"
        | "Asia/Krasnoyarsk"
        | "Asia/Kuala_Lumpur"
        | "Asia/Kuching"
        | "Asia/Kuwait"
        | "Asia/Macao"
        | "Asia/Macau"
        | "Asia/Magadan"
        | "Asia/Makassar"
        | "Asia/Manila"
        | "Asia/Muscat"
        | "Asia/Nicosia"
        | "Asia/Novokuznetsk"
        | "Asia/Novosibirsk"
        | "Asia/Omsk"
        | "Asia/Oral"
        | "Asia/Phnom_Penh"
        | "Asia/Pontianak"
        | "Asia/Pyongyang"
        | "Asia/Qatar"
        | "Asia/Qostanay"
        | "Asia/Qyzylorda"
        | "Asia/Rangoon"
        | "Asia/Riyadh"
        | "Asia/Saigon"
        | "Asia/Sakhalin"
        | "Asia/Samarkand"
        | "Asia/Seoul"
        | "Asia/Shanghai"
        | "Asia/Singapore"
        | "Asia/Srednekolymsk"
        | "Asia/Taipei"
        | "Asia/Tashkent"
        | "Asia/Tbilisi"
        | "Asia/Tehran"
        | "Asia/Tel_Aviv"
        | "Asia/Thimbu"
        | "Asia/Thimphu"
        | "Asia/Tokyo"
        | "Asia/Tomsk"
        | "Asia/Ujung_Pandang"
        | "Asia/Ulaanbaatar"
        | "Asia/Ulan_Bator"
        | "Asia/Urumqi"
        | "Asia/Ust-Nera"
        | "Asia/Vientiane"
        | "Asia/Vladivostok"
        | "Asia/Yakutsk"
        | "Asia/Yangon"
        | "Asia/Yekaterinburg"
        | "Asia/Yerevan"
        | "Atlantic/Azores"
        | "Atlantic/Bermuda"
        | "Atlantic/Canary"
        | "Atlantic/Cape_Verde"
        | "Atlantic/Faeroe"
        | "Atlantic/Faroe"
        | "Atlantic/Jan_Mayen"
        | "Atlantic/Madeira"
        | "Atlantic/Reykjavik"
        | "Atlantic/South_Georgia"
        | "Atlantic/St_Helena"
        | "Atlantic/Stanley"
        | "Australia/ACT"
        | "Australia/Adelaide"
        | "Australia/Brisbane"
        | "Australia/Broken_Hill"
        | "Australia/Canberra"
        | "Australia/Currie"
        | "Australia/Darwin"
        | "Australia/Eucla"
        | "Australia/Hobart"
        | "Australia/LHI"
        | "Australia/Lindeman"
        | "Australia/Lord_Howe"
        | "Australia/Melbourne"
        | "Australia/NSW"
        | "Australia/North"
        | "Australia/Perth"
        | "Australia/Queensland"
        | "Australia/South"
        | "Australia/Sydney"
        | "Australia/Tasmania"
        | "Australia/Victoria"
        | "Australia/West"
        | "Australia/Yancowinna"
        | "Brazil/Acre"
        | "Brazil/DeNoronha"
        | "Brazil/East"
        | "Brazil/West"
        | "CET"
        | "CST6CDT"
        | "Canada/Atlantic"
        | "Canada/Central"
        | "Canada/Eastern"
        | "Canada/Mountain"
        | "Canada/Newfoundland"
        | "Canada/Pacific"
        | "Canada/Saskatchewan"
        | "Canada/Yukon"
        | "Chile/Continental"
        | "Chile/EasterIsland"
        | "Cuba"
        | "EET"
        | "EST"
        | "EST5EDT"
        | "Egypt"
        | "Eire"
        | "Etc/GMT"
        | "Etc/GMT+0"
        | "Etc/GMT+1"
        | "Etc/GMT+10"
        | "Etc/GMT+11"
        | "Etc/GMT+12"
        | "Etc/GMT+2"
        | "Etc/GMT+3"
        | "Etc/GMT+4"
        | "Etc/GMT+5"
        | "Etc/GMT+6"
        | "Etc/GMT+7"
        | "Etc/GMT+8"
        | "Etc/GMT+9"
        | "Etc/GMT-0"
        | "Etc/GMT-1"
        | "Etc/GMT-10"
        | "Etc/GMT-11"
        | "Etc/GMT-12"
        | "Etc/GMT-13"
        | "Etc/GMT-14"
        | "Etc/GMT-2"
        | "Etc/GMT-3"
        | "Etc/GMT-4"
        | "Etc/GMT-5"
        | "Etc/GMT-6"
        | "Etc/GMT-7"
        | "Etc/GMT-8"
        | "Etc/GMT-9"
        | "Etc/GMT0"
        | "Etc/Greenwich"
        | "Etc/UCT"
        | "Etc/UTC"
        | "Etc/Universal"
        | "Etc/Zulu"
        | "Europe/Amsterdam"
        | "Europe/Andorra"
        | "Europe/Astrakhan"
        | "Europe/Athens"
        | "Europe/Belfast"
        | "Europe/Belgrade"
        | "Europe/Berlin"
        | "Europe/Bratislava"
        | "Europe/Brussels"
        | "Europe/Bucharest"
        | "Europe/Budapest"
        | "Europe/Busingen"
        | "Europe/Chisinau"
        | "Europe/Copenhagen"
        | "Europe/Dublin"
        | "Europe/Gibraltar"
        | "Europe/Guernsey"
        | "Europe/Helsinki"
        | "Europe/Isle_of_Man"
        | "Europe/Istanbul"
        | "Europe/Jersey"
        | "Europe/Kaliningrad"
        | "Europe/Kiev"
        | "Europe/Kirov"
        | "Europe/Kyiv"
        | "Europe/Lisbon"
        | "Europe/Ljubljana"
        | "Europe/London"
        | "Europe/Luxembourg"
        | "Europe/Madrid"
        | "Europe/Malta"
        | "Europe/Mariehamn"
        | "Europe/Minsk"
        | "Europe/Monaco"
        | "Europe/Moscow"
        | "Europe/Nicosia"
        | "Europe/Oslo"
        | "Europe/Paris"
        | "Europe/Podgorica"
        | "Europe/Prague"
        | "Europe/Riga"
        | "Europe/Rome"
        | "Europe/Samara"
        | "Europe/San_Marino"
        | "Europe/Sarajevo"
        | "Europe/Saratov"
        | "Europe/Simferopol"
        | "Europe/Skopje"
        | "Europe/Sofia"
        | "Europe/Stockholm"
        | "Europe/Tallinn"
        | "Europe/Tirane"
        | "Europe/Tiraspol"
        | "Europe/Ulyanovsk"
        | "Europe/Uzhgorod"
        | "Europe/Vaduz"
        | "Europe/Vatican"
        | "Europe/Vienna"
        | "Europe/Vilnius"
        | "Europe/Volgograd"
        | "Europe/Warsaw"
        | "Europe/Zagreb"
        | "Europe/Zaporozhye"
        | "Europe/Zurich"
        | "GB"
        | "GB-Eire"
        | "GMT"
        | "GMT+0"
        | "GMT-0"
        | "GMT0"
        | "Greenwich"
        | "HST"
        | "Hongkong"
        | "Iceland"
        | "Indian/Antananarivo"
        | "Indian/Chagos"
        | "Indian/Christmas"
        | "Indian/Cocos"
        | "Indian/Comoro"
        | "Indian/Kerguelen"
        | "Indian/Mahe"
        | "Indian/Maldives"
        | "Indian/Mauritius"
        | "Indian/Mayotte"
        | "Indian/Reunion"
        | "Iran"
        | "Israel"
        | "Jamaica"
        | "Japan"
        | "Kwajalein"
        | "Libya"
        | "MET"
        | "MST"
        | "MST7MDT"
        | "Mexico/BajaNorte"
        | "Mexico/BajaSur"
        | "Mexico/General"
        | "NZ"
        | "NZ-CHAT"
        | "Navajo"
        | "PRC"
        | "PST8PDT"
        | "Pacific/Apia"
        | "Pacific/Auckland"
        | "Pacific/Bougainville"
        | "Pacific/Chatham"
        | "Pacific/Chuuk"
        | "Pacific/Easter"
        | "Pacific/Efate"
        | "Pacific/Enderbury"
        | "Pacific/Fakaofo"
        | "Pacific/Fiji"
        | "Pacific/Funafuti"
        | "Pacific/Galapagos"
        | "Pacific/Gambier"
        | "Pacific/Guadalcanal"
        | "Pacific/Guam"
        | "Pacific/Honolulu"
        | "Pacific/Johnston"
        | "Pacific/Kanton"
        | "Pacific/Kiritimati"
        | "Pacific/Kosrae"
        | "Pacific/Kwajalein"
        | "Pacific/Majuro"
        | "Pacific/Marquesas"
        | "Pacific/Midway"
        | "Pacific/Nauru"
        | "Pacific/Niue"
        | "Pacific/Norfolk"
        | "Pacific/Noumea"
        | "Pacific/Pago_Pago"
        | "Pacific/Palau"
        | "Pacific/Pitcairn"
        | "Pacific/Pohnpei"
        | "Pacific/Ponape"
        | "Pacific/Port_Moresby"
        | "Pacific/Rarotonga"
        | "Pacific/Saipan"
        | "Pacific/Samoa"
        | "Pacific/Tahiti"
        | "Pacific/Tarawa"
        | "Pacific/Tongatapu"
        | "Pacific/Truk"
        | "Pacific/Wake"
        | "Pacific/Wallis"
        | "Pacific/Yap"
        | "Poland"
        | "Portugal"
        | "ROC"
        | "ROK"
        | "Singapore"
        | "Turkey"
        | "UCT"
        | "US/Alaska"
        | "US/Aleutian"
        | "US/Arizona"
        | "US/Central"
        | "US/East-Indiana"
        | "US/Eastern"
        | "US/Hawaii"
        | "US/Indiana-Starke"
        | "US/Michigan"
        | "US/Mountain"
        | "US/Pacific"
        | "US/Samoa"
        | "UTC"
        | "Universal"
        | "W-SU"
        | "WET"
        | "Zulu";
    /**
     * Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.
     * Also used for nested serializers.
     */
    export type TeamBasic = {
        id: number;
        uuid: string;
        organization: string;
        project_id: number;
        api_token: string;
        name: string;
        completed_snippet_onboarding: boolean;
        has_completed_onboarding_for: unknown;
        ingested_event: boolean;
        is_demo: boolean;
        timezone: TimezoneEnum & unknown;
        access_control: boolean;
    };
    export type ScenePersonalisationBasic = {
        scene: string;
        dashboard?: (number | null) | undefined;
    };
    /**
     * * `light` - Light
     * * `dark` - Dark
     * * `system` - System
     */
    export type ThemeModeEnum = "light" | "dark" | "system";
    /**
     * * `above` - Above
     * * `below` - Below
     * * `hidden` - Hidden
     */
    export type ShortcutPositionEnum = "above" | "below" | "hidden";
    /**
     * Shape of each item in UserSerializer.pending_invites.
     */
    export type PendingInvite = {
        id: string;
        target_email: string;
        organization_id: string;
        organization_name: string;
        created_at: string;
    };
    export type User = {
        date_joined: string;
        uuid: string;
        distinct_id: string | null;
        first_name?: string | undefined;
        last_name?: string | undefined;
        email: string;
        pending_email: string | null;
        is_email_verified: boolean | null;
        notification_settings?: Record<string, unknown> | undefined;
        /**
         * Notification settings an organization admin enforces on this user. The matching controls are read-only, and `notification_settings` still holds the user's own choice underneath. Read-only.
         */
        notification_locks: Array<OrganizationNotificationLock>;
        anonymize_data?: (boolean | null) | undefined;
        allow_impersonation?: (boolean | null) | undefined;
        toolbar_mode?: (ToolbarModeEnum | BlankEnum | NullEnum) | undefined;
        has_password: boolean;
        id: number;
        is_staff?: boolean | undefined;
        is_impersonated: boolean | null;
        is_impersonated_until: string | null;
        is_impersonated_read_only: boolean | null;
        /**
         * The reason the operator gave when the current impersonation session started (or was last up/downgraded). Null when not impersonating.
         */
        is_impersonated_reason: string | null;
        sensitive_session_expires_at: string | null;
        team: TeamBasic & unknown;
        organization: Organization & unknown;
        organizations: Array<OrganizationBasic>;
        set_current_organization?: string | undefined;
        set_current_team?: string | undefined;
        password: string;
        current_password?: string | undefined;
        events_column_config?: unknown | undefined;
        is_2fa_enabled: boolean;
        has_social_auth: boolean;
        has_sso_enforcement: boolean;
        has_seen_product_intro_for?: unknown | undefined;
        scene_personalisation: Array<ScenePersonalisationBasic>;
        theme_mode?: (ThemeModeEnum | BlankEnum | NullEnum) | undefined;
        hedgehog_config?: unknown | undefined;
        allow_sidebar_suggestions?: (boolean | null) | undefined;
        shortcut_position?:
            | (ShortcutPositionEnum | BlankEnum | NullEnum)
            | undefined;
        role_at_organization?: RoleAtOrganizationEnum | undefined;
        passkeys_enabled_for_2fa?: (boolean | null) | undefined;
        hide_mcp_hints?: boolean | undefined;
        ui_configuration?: unknown | undefined;
        onboarding_skipped_at: string | null;
        onboarding_skipped_reason: OnboardingSkippedReasonEnum | NullEnum;
        onboarding_skipped_organization_id: string | null;
        onboarding_delegated_to_invite: string | null;
        /**
         * Organization ID of the pending delegation invite, if any. Used by the frontend to scope the 'waiting for teammate' UI to the org where delegation was initiated.
         */
        onboarding_delegated_to_organization_id: string | null;
        onboarding_delegation_accepted_at: string | null;
        is_organization_first_user: boolean | null;
        /**
         * Real-time notification types that currently have a live dispatch site. Drives the in-app notifications settings UI. Read-only.
         */
        active_realtime_notification_types: Array<string>;
        pending_invites: Array<PendingInvite>;
        /**
         * True if the user has at least one Personal API Key or passkey, or a third-party OAuth application that can currently act as them, and has not yet acknowledged that access. Used to gate a one-shot review screen on first post-provisioning login. Becomes False once the user POSTs to `/api/users/@me/credentials_review_complete/`. Read-only.
         */
        requires_credential_review: boolean;
    };
    export type PaginatedUserList = {
        count: number;
        next?: (string | null) | undefined;
        previous?: (string | null) | undefined;
        results: Array<User>;
    };
    /**
     * Serializer mixin that handles tags for objects.
     */
    export type PatchedAction = Partial<{
        id: number;
        name: string | null;
        description: string;
        tags: Array<unknown>;
        post_to_slack: boolean;
        slack_message_format: string;
        steps: Array<ActionStepJSON>;
        created_at: string;
        created_by: UserBasic & unknown;
        deleted: boolean;
        is_calculating: boolean;
        last_calculated_at: string;
        team_id: number;
        is_action: boolean;
        bytecode_error: string | null;
        pinned_at: string | null;
        creation_context: string | null;
        _create_in_folder: string;
        user_access_level: string | null;
    }>;
    export type PatchedCohort = Partial<{
        id: number;
        name: string | null;
        description: string;
        groups: unknown;
        deleted: boolean;
        filters: CohortFilters | null;
        query: unknown;
        version: number | null;
        pending_version: number | null;
        is_calculating: boolean;
        created_by: UserBasic & unknown;
        created_at: string | null;
        last_calculation: string | null;
        last_backfill_person_properties_at: string | null;
        errors_calculating: number;
        last_error_message: string | null;
        count: number | null;
        last_import_total_count: number | null;
        last_import_unmatched_count: number | null;
        is_static: boolean;
        cohort_type: CohortTypeEnum | BlankEnum | NullEnum;
        condition_type: CohortConditionTypeFlags | null;
        experiment_set: Array<number>;
        search_match_type: SearchMatchTypeEnum | NullEnum;
        _create_in_folder: string;
        _create_static_person_ids: Array<string>;
    }>;
    export type PatchedErrorTrackingIssueWrite = Partial<{
        status: ErrorTrackingIssueWriteStatusEnum;
        severity: ErrorTrackingIssueSeverity | null;
        name: string | null;
        description: string | null;
    }>;
    /**
     * An evaluation that scores LLM generations, traces, or sessions.
     */
    export type PatchedEvaluation = Partial<{
        id: string;
        name: string;
        description: string;
        directory_id: string | null;
        enabled: boolean;
        status: EvaluationStatusEnum & unknown;
        status_reason: EvaluationStatusReasonEnum | NullEnum;
        status_reason_detail: string | null;
        evaluation_type: EvaluationTypeEnum;
        evaluation_config:
            | { prompt: string }
            | { source: string }
            | Partial<{ source: "user_messages" }>;
        output_type: OutputTypeEnum;
        output_config: Partial<{ allows_na: boolean }>;
        conditions: Array<EvaluationCondition>;
        target: EvaluationTargetEnum;
        target_config:
            | { strategy: "fixed_window"; window_seconds?: number | undefined }
            | {
                  strategy: "inactivity";
                  quiet_period_seconds?: number | undefined;
                  max_age_seconds?: number | undefined;
              };
        model_configuration: ModelConfiguration | null;
        created_at: string;
        updated_at: string;
        created_by: UserBasic | null;
        deleted: boolean;
        user_access_level: string | null;
    }>;
    /**
     * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
     */
    export type PatchedExperimentWrite = Partial<{
        id: number;
        name: string;
        description: string | null;
        start_date: string | null;
        end_date: string | null;
        feature_flag_key: string;
        feature_flag: ExperimentFeatureFlagInput;
        holdout: ExperimentHoldout & unknown;
        holdout_id: number | null;
        exposure_cohort: number | null;
        parameters: ExperimentParameters | null;
        running_time_calculation: ExperimentRunningTimeCalculation | null;
        excluded_variants: Array<string> | null;
        secondary_metrics: unknown;
        saved_metrics: Array<ExperimentToSavedMetric>;
        saved_metrics_ids: Array<unknown> | null;
        filters: unknown;
        archived: boolean;
        deleted: boolean | null;
        created_by: UserBasic & unknown;
        created_at: string;
        updated_at: string;
        type: ExperimentTypeEnum | NullEnum;
        exposure_criteria: ExperimentApiExposureCriteria | null;
        metrics: _ExperimentApiMetricsList | null;
        metrics_secondary: _ExperimentApiMetricsList | null;
        stats_config: unknown;
        scheduling_config: unknown;
        allow_unknown_events: boolean;
        _create_in_folder: string;
        conclusion: ConclusionEnum | NullEnum;
        conclusion_comment: string | null;
        flag_cleanup_task_id: string | null;
        repository: string | null;
        primary_metrics_ordered_uuids: unknown;
        secondary_metrics_ordered_uuids: unknown;
        only_count_matured_users: boolean;
        update_feature_flag_params: boolean;
        version: number | null;
        original_experiment: Record<string, unknown> | null;
        status: ExperimentStatusEnum & unknown;
        is_legacy: boolean;
        can_freeze_exposure: boolean;
        resolved_exposure_event: string;
        user_access_level: string | null;
    }>;
    export type PatchedExternalDataSourceBulkUpdateSchemas = Partial<{
        schemas: Array<ExternalDataSourceBulkUpdateSchema>;
    }>;
    /**
     * Mixin for serializers to add user access control fields
     */
    export type PatchedExternalDataSourceSerializers = Partial<{
        id: string;
        created_at: string;
        created_by: string | null;
        created_via: ExternalDataSourceCreatedViaEnum | NullEnum;
        status: string;
        client_secret: string;
        account_id: string;
        source_type: ExternalDataSourceTypeEnum & unknown;
        latest_error: string | null;
        prefix: string | null;
        description: string | null;
        access_method: ExternalDataSourceAccessMethodEnum & unknown;
        direct_query_enabled: boolean;
        auto_sync_new_schemas: boolean;
        auto_sync_schema_patterns: Array<string> | null;
        engine: EngineEnum | NullEnum;
        last_run_at: string | null;
        schemas: Array<Record<string, unknown>>;
        job_inputs: unknown;
        revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfig &
            unknown;
        user_access_level: string | null;
        supports_webhooks: boolean;
        supports_column_selection: boolean;
        api_version: string | null;
        api_version_deprecation: ExternalDataSourceApiVersionDeprecation | null;
    }>;
    export type PatchedFeatureFlagPartialUpdateRequestSchema = Partial<{
        key: string;
        name: string;
        filters: FeatureFlagFiltersSchema;
        active: boolean;
        archived: boolean;
        tags: Array<string>;
        evaluation_contexts: Array<string>;
        is_remote_configuration: boolean | null;
        ensure_experience_continuity: boolean | null;
        evaluation_runtime: EvaluationRuntimeEnum | NullEnum;
        bucketing_identifier: BucketingIdentifierEnum | NullEnum;
    }>;
    export type PatchedHogFlowSchedule = Partial<{
        id: string;
        rrule: string;
        starts_at: string;
        timezone: string;
        variables: unknown;
        status: HogFlowScheduleStatusEnum & unknown;
        next_run_at: string | null;
        created_at: string;
        updated_at: string;
    }>;
    /**
     * Mixin for serializers to add user access control fields
     */
    export type PatchedHogFlowUpdate = Partial<{
        id: string;
        name: string | null;
        description: string;
        version: number;
        status: HogFlowStateEnum;
        origin_product: HogFlowOriginProductEnum | NullEnum;
        created_at: string;
        created_by: UserBasic & unknown;
        updated_at: string;
        trigger: unknown;
        trigger_masking: HogFlowMasking | null;
        conversion: HogFlowConversion | null;
        exit_condition: ExitConditionEnum;
        email_sending_rate_limit: HogFlowEmailSendingRateLimit | null;
        edges: Array<HogFlowEdge>;
        actions: Array<HogFlowAction>;
        abort_action: string | null;
        variables: Array<Record<string, string>>;
        billable_action_types: unknown;
        schedules: Array<HogFlowSchedule>;
        user_access_level: string | null;
        draft: unknown;
        draft_updated_at: string | null;
        action_redirects: Record<string, string> | null;
    }>;
    /**
     * Simplified serializer to speed response times when loading large amounts of objects.
     */
    export type PatchedInsight = Partial<{
        id: number;
        short_id: string;
        name: string | null;
        derived_name: string | null;
        query: _InsightQuerySchema | null;
        order: number | null;
        deleted: boolean;
        dashboards: Array<number>;
        dashboard_tiles: Array<DashboardTileBasic>;
        last_refresh: string | null;
        cache_target_age: string | null;
        next_allowed_client_refresh: string | null;
        result: unknown;
        hasMore: boolean | null;
        columns: Array<string> | null;
        created_at: string | null;
        created_by: UserBasic & unknown;
        description: string | null;
        updated_at: string;
        tags: Array<unknown>;
        favorited: boolean;
        last_modified_at: string;
        last_modified_by: UserBasic & unknown;
        is_sample: boolean;
        effective_restriction_level: RestrictionLevelEnum & unknown;
        effective_privilege_level: PrivilegeLevelEnum & unknown;
        user_access_level: string | null;
        timezone: string | null;
        is_cached: boolean;
        query_status: unknown;
        hogql: string | null;
        types: Array<unknown> | null;
        resolved_date_range: Partial<{
            date_from: string;
            date_to: string;
        }> | null;
        _create_in_folder: string;
        alerts: Array<unknown>;
        filter_override_context: InsightFilterOverrideContext | null;
        last_viewed_at: string | null;
        search_match_type: SearchMatchTypeEnum | NullEnum;
    }>;
    /**
     * OpenAPI-only PATCH body for dashboards (agents/MCP).
     *
     * Must be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``
     * replaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.
     */
    export type PatchedPatchedDashboardOpenApi = Partial<{
        name: string | null;
        description: string;
        pinned: boolean;
        filters: DashboardFiltersOpenApi;
        breakdown_colors: unknown;
        data_color_theme_id: number | null;
        tags: Array<string>;
        restriction_level: RestrictionLevelEnum;
        quick_filter_ids: Array<string> | null;
        grid_spacing: TileSpacingEnum;
        layout_compaction: LayoutCompactionEnum;
        tiles: Array<DashboardPatchTileOpenApi>;
        use_template: string;
        use_dashboard: number | null;
        delete_insights: boolean;
    }>;
    export type PatchedPersonRecord = Partial<{
        id: number;
        name: string;
        distinct_ids: Array<string>;
        properties: unknown;
        created_at: string;
        uuid: string;
        last_seen_at: string | null;
    }>;
    export type PatchedSessionRecording = Partial<{
        id: string;
        distinct_id: string | null;
        viewed: boolean;
        viewers: Array<string>;
        recording_duration: number;
        active_seconds: number | null;
        inactive_seconds: number | null;
        start_time: string | null;
        end_time: string | null;
        click_count: number | null;
        keypress_count: number | null;
        mouse_activity_count: number | null;
        console_log_count: number | null;
        console_warn_count: number | null;
        console_error_count: number | null;
        start_url: string | null;
        person: MinimalPerson;
        retention_period_days: number | null;
        expiry_time: string | null;
        recording_ttl: number | null;
        snapshot_source: string | null;
        snapshot_library: string | null;
        ongoing: boolean;
        activity_score: number | null;
        external_references: Array<Record<string, unknown>>;
        matches_filters: boolean;
        total_size: number | null;
        event_count: number | null;
    }>;
    /**
     * * `popover` - popover
     * * `widget` - widget
     * * `external_survey` - external survey
     * * `api` - api
     */
    export type SurveyTypeEnum =
        | "popover"
        | "widget"
        | "external_survey"
        | "api";
    /**
     * * `once` - once
     * * `recurring` - recurring
     * * `always` - always
     */
    export type SurveyScheduleEnum = "once" | "recurring" | "always";
    /**
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     */
    export type SurveyMatchTypeEnum =
        | "regex"
        | "not_regex"
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains";
    export type SurveyConditionEventValueSchema = {
        /**
         * Event name that triggers the survey.
         */
        name: string;
    };
    export type SurveyEventsConditionSchema = Partial<{
        repeatedActivation: boolean;
        values: Array<SurveyConditionEventValueSchema>;
    }>;
    export type SurveyConditionsSchema = Partial<{
        url: string;
        selector: string;
        seenSurveyWaitPeriodInDays: number;
        urlMatchType: SurveyMatchTypeEnum;
        events: SurveyEventsConditionSchema;
        deviceTypes: Array<DeviceTypesEnum>;
        deviceTypesMatchType: SurveyMatchTypeEnum;
        linkedFlagVariant: string;
    }>;
    /**
     * * `button` - button
     * * `tab` - tab
     * * `selector` - selector
     */
    export type WidgetTypeEnum = "button" | "tab" | "selector";
    export type SurveyAppearanceSchema = Partial<{
        backgroundColor: string;
        submitButtonColor: string;
        textColor: string;
        submitButtonText: string;
        submitButtonTextColor: string;
        descriptionTextColor: string;
        ratingButtonColor: string;
        ratingButtonActiveColor: string;
        ratingButtonHoverColor: string;
        whiteLabel: boolean;
        autoDisappear: boolean;
        displayThankYouMessage: boolean;
        thankYouMessageHeader: string;
        thankYouMessageDescription: string;
        thankYouMessageDescriptionContentType: DescriptionContentTypeEnum;
        thankYouMessageCloseButtonText: string;
        borderColor: string;
        placeholder: string;
        shuffleQuestions: boolean;
        surveyPopupDelaySeconds: number;
        allowGoBack: boolean;
        backButtonText: string;
        widgetType: WidgetTypeEnum;
        widgetSelector: string;
        widgetLabel: string;
        widgetColor: string;
        fontFamily: string;
        maxWidth: string;
        zIndex: string;
        disabledButtonOpacity: string;
        boxPadding: string;
    }>;
    /**
     * * `day` - day
     * * `week` - week
     * * `month` - month
     */
    export type SurveySamplingIntervalTypeEnum = "day" | "week" | "month";
    export type PatchedSurveySerializerCreateUpdateOnlySchema = Partial<{
        id: string;
        name: string;
        description: string;
        type: SurveyTypeEnum;
        schedule: SurveyScheduleEnum | NullEnum;
        linked_flag: MinimalFeatureFlag & unknown;
        linked_flag_id: number | null;
        linked_insight_id: number | null;
        targeting_flag_id: number;
        targeting_flag: MinimalFeatureFlag & unknown;
        internal_targeting_flag: MinimalFeatureFlag & unknown;
        targeting_flag_filters: FeatureFlagFiltersSchema | null;
        remove_targeting_flag: boolean | null;
        questions: Array<SurveyQuestionInputSchema> | null;
        conditions: SurveyConditionsSchema | null;
        appearance: SurveyAppearanceSchema | null;
        created_at: string;
        created_by: UserBasic & unknown;
        start_date: string | null;
        end_date: string | null;
        archived: boolean;
        responses_limit: number | null;
        iteration_count: number | null;
        iteration_frequency_days: number | null;
        iteration_start_dates: Array<string | null> | null;
        current_iteration: number | null;
        current_iteration_start_date: string | null;
        response_sampling_start_date: string | null;
        response_sampling_interval_type:
            | SurveySamplingIntervalTypeEnum
            | BlankEnum
            | NullEnum;
        response_sampling_interval: number | null;
        response_sampling_limit: number | null;
        response_sampling_daily_limits: unknown;
        enable_partial_responses: boolean | null;
        enable_iframe_embedding: boolean | null;
        base_language: string;
        translations: unknown;
        _create_in_folder: string;
        form_content: unknown;
    }>;
    /**
     * * `not_started` - not_started
     * * `queued` - queued
     * * `in_progress` - in_progress
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled
     */
    export type RunStatusEnum =
        | "not_started"
        | "queued"
        | "in_progress"
        | "completed"
        | "failed"
        | "cancelled";
    export type PatchedTaskRunUpdate = Partial<{
        status: RunStatusEnum;
        branch: string | null;
        stage: string | null;
        output: unknown;
        state: unknown;
        state_remove_keys: Array<string>;
        state_append: Record<string, unknown>;
        error_message: string | null;
    }>;
    /**
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `experiments` - Experiments
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `scout_suggestions` - Signals Scout Suggestions
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk
     * * `review_hog` - ReviewHog
     * * `image_builder` - Image Builder
     * * `loop` - Loop
     * * `mcp_analytics` - MCP Analytics
     * * `signals_chat` - Signals Chat
     * * `task_analysis` - Task Analysis
     * * `workflow` - Workflow
     */
    export type TaskOriginProductEnum =
        | "onboarding"
        | "error_tracking"
        | "eval_clusters"
        | "user_created"
        | "slack"
        | "support_queue"
        | "session_summaries"
        | "posthog_ai"
        | "experiments"
        | "signal_report"
        | "signals_scout"
        | "scout_suggestions"
        | "support_reply"
        | "hogdesk"
        | "review_hog"
        | "image_builder"
        | "loop"
        | "mcp_analytics"
        | "signals_chat"
        | "task_analysis"
        | "workflow";
    /**
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access
     */
    export type TaskRunBootstrapCreateRequestInitialPermissionModeEnum =
        | "default"
        | "acceptEdits"
        | "plan"
        | "bypassPermissions"
        | "auto"
        | "read-only"
        | "full-access";
    /**
     * Request body for creating or updating a task.
     *
     * Field required/default semantics match the ``Task`` model. The view passes
     * ``validated_data`` (integration/report PK fields already resolved to instances) to the
     * facade ``create_task`` / ``update_task`` functions.
     */
    export type PatchedTaskWrite = Partial<{
        title: string;
        title_manually_set: boolean;
        description: string;
        origin_product: TaskOriginProductEnum;
        repository: string | null;
        repositories: Array<string>;
        github_integration: number | null;
        github_user_integration: string | null;
        signal_report: string | null;
        signal_report_task_relationship: string;
        json_schema: unknown;
        archived: boolean;
        ci_prompt: string | null;
        branch: string | null;
        runtime_adapter: RuntimeAdapterEnum | NullEnum;
        model: string | null;
        reasoning_effort: ReasoningEffortEnum | NullEnum;
        initial_permission_mode:
            | TaskRunBootstrapCreateRequestInitialPermissionModeEnum
            | NullEnum;
        pending_user_message: string | null;
        pending_user_artifact_ids: Array<string>;
        auto_publish: boolean | null;
        channel: string | null;
    }>;
    /**
     * * `new` - New
     * * `open` - Open
     * * `pending` - Pending
     * * `on_hold` - On hold
     * * `resolved` - Resolved
     */
    export type TicketStatusEnum =
        | "new"
        | "open"
        | "pending"
        | "on_hold"
        | "resolved";
    /**
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `critical` - Critical
     */
    export type TicketPriorityEnum = "low" | "medium" | "high" | "critical";
    export type UserTicketAssigneeRequest = {
        /**
         * Assign the ticket to a user.
         */
        type: string;
        /**
         * User ID.
         */
        id: number;
    };
    export type RoleTicketAssigneeRequest = {
        /**
         * Assign the ticket to a role.
         */
        type: string;
        /**
         * Role ID.
         */
        id: string;
    };
    export type TicketAssigneeRequest =
        | UserTicketAssigneeRequest
        | RoleTicketAssigneeRequest;
    /**
     * Fields accepted when updating a ticket.
     */
    export type PatchedTicketUpdateRequest = Partial<{
        status: TicketStatusEnum;
        priority: TicketPriorityEnum | BlankEnum | NullEnum;
        assignee: TicketAssigneeRequest | null;
        anonymous_traits: unknown;
        ai_resolved: boolean;
        escalation_reason: string | null;
        sla_due_at: string | null;
        snoozed_until: string | null;
        tags: Array<string>;
    }>;
    export type PatchedUser = Partial<{
        date_joined: string;
        uuid: string;
        distinct_id: string | null;
        first_name: string;
        last_name: string;
        email: string;
        pending_email: string | null;
        is_email_verified: boolean | null;
        notification_settings: Record<string, unknown>;
        notification_locks: Array<OrganizationNotificationLock>;
        anonymize_data: boolean | null;
        allow_impersonation: boolean | null;
        toolbar_mode: ToolbarModeEnum | BlankEnum | NullEnum;
        has_password: boolean;
        id: number;
        is_staff: boolean;
        is_impersonated: boolean | null;
        is_impersonated_until: string | null;
        is_impersonated_read_only: boolean | null;
        is_impersonated_reason: string | null;
        sensitive_session_expires_at: string | null;
        team: TeamBasic & unknown;
        organization: Organization & unknown;
        organizations: Array<OrganizationBasic>;
        set_current_organization: string;
        set_current_team: string;
        password: string;
        current_password: string;
        events_column_config: unknown;
        is_2fa_enabled: boolean;
        has_social_auth: boolean;
        has_sso_enforcement: boolean;
        has_seen_product_intro_for: unknown;
        scene_personalisation: Array<ScenePersonalisationBasic>;
        theme_mode: ThemeModeEnum | BlankEnum | NullEnum;
        hedgehog_config: unknown;
        allow_sidebar_suggestions: boolean | null;
        shortcut_position: ShortcutPositionEnum | BlankEnum | NullEnum;
        role_at_organization: RoleAtOrganizationEnum;
        passkeys_enabled_for_2fa: boolean | null;
        hide_mcp_hints: boolean;
        ui_configuration: unknown;
        onboarding_skipped_at: string | null;
        onboarding_skipped_reason: OnboardingSkippedReasonEnum | NullEnum;
        onboarding_skipped_organization_id: string | null;
        onboarding_delegated_to_invite: string | null;
        onboarding_delegated_to_organization_id: string | null;
        onboarding_delegation_accepted_at: string | null;
        is_organization_first_user: boolean | null;
        active_realtime_notification_types: Array<string>;
        pending_invites: Array<PendingInvite>;
        requires_credential_review: boolean;
    }>;
    /**
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `starts_with` - starts_with
     * * `not_starts_with` - not_starts_with
     * * `ends_with` - ends_with
     * * `not_ends_with` - not_ends_with
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `lt` - lt
     * * `gte` - gte
     * * `lte` - lte
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set
     * * `is_date_exact` - is_date_exact
     * * `is_date_after` - is_date_after
     * * `is_date_before` - is_date_before
     * * `in` - in
     * * `not_in` - not_in
     */
    export type PropertyItemOperatorEnum =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "starts_with"
        | "not_starts_with"
        | "ends_with"
        | "not_ends_with"
        | "regex"
        | "not_regex"
        | "gt"
        | "lt"
        | "gte"
        | "lte"
        | "is_set"
        | "is_not_set"
        | "is_date_exact"
        | "is_date_after"
        | "is_date_before"
        | "in"
        | "not_in";
    export type PropertyItem = {
        /**
         * Key of the property you're filtering on. For example `email` or `$current_url`
         */
        key: string;
        /**
         * Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]`
         */
        value: string | number | boolean | Array<string | number>;
        operator?:
            | (PropertyItemOperatorEnum | BlankEnum | NullEnum)
            | undefined;
        type?: (PropertyFilterTypeEnum | BlankEnum) | undefined;
    };
    export type Property = {
        type?: (PropertyGroupOperatorEnum & unknown) | undefined;
        values: Array<PropertyItem>;
    };
    /**
     * One desktop-only MCP server relayed into the run — a name only, never configuration.
     */
    export type RelayedMcpServer = { name: string };
    export type SessionRecording = {
        id: string;
        distinct_id: string | null;
        viewed: boolean;
        viewers: Array<string>;
        recording_duration: number;
        active_seconds: number | null;
        inactive_seconds: number | null;
        start_time: string | null;
        end_time: string | null;
        click_count: number | null;
        keypress_count: number | null;
        mouse_activity_count: number | null;
        console_log_count: number | null;
        console_warn_count: number | null;
        console_error_count: number | null;
        start_url: string | null;
        person?: MinimalPerson | undefined;
        retention_period_days: number | null;
        expiry_time: string | null;
        recording_ttl: number | null;
        snapshot_source: string | null;
        snapshot_library: string | null;
        ongoing: boolean;
        activity_score: number | null;
        /**
         * Load external references (linked issues) for this recording
         */
        external_references: Array<Record<string, unknown>>;
        /**
         * Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters.
         */
        matches_filters: boolean;
        /**
         * Total stored size of the recording's snapshot data in bytes. Only populated when the recording's metadata is loaded, e.g. on retrieve; null in list responses.
         */
        total_size: number | null;
        /**
         * Number of captured rrweb events in the recording. Only populated when the recording's metadata is loaded, e.g. on retrieve; null in list responses.
         */
        event_count: number | null;
    };
    /**
     * * `30d` - 30 Days
     * * `90d` - 90 Days
     * * `1y` - 1 Year
     * * `5y` - 5 Years
     */
    export type SessionRecordingRetentionPeriodEnum =
        | "30d"
        | "90d"
        | "1y"
        | "5y";
    /**
     * Mixin for serializers to add user access control fields
     */
    export type Survey = {
        id: string;
        name: string;
        /**
         * Mixin for serializers to add user access control fields
         */
        description?: string | undefined;
        type: SurveyTypeEnum;
        /**
         * Mixin for serializers to add user access control fields
         */
        schedule?: (string | null) | undefined;
        linked_flag: MinimalFeatureFlag & unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        linked_flag_id?: (number | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        linked_insight_id?: (number | null) | undefined;
        targeting_flag: MinimalFeatureFlag & unknown;
        internal_targeting_flag: MinimalFeatureFlag & unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        questions?: unknown | undefined;
        conditions: Record<string, unknown> | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        appearance?: unknown | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        start_date?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        end_date?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        archived?: boolean | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        responses_limit?: (number | null) | undefined;
        feature_flag_keys: Array<Record<string, string | null>>;
        /**
         * Mixin for serializers to add user access control fields
         */
        iteration_count?: (number | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        iteration_frequency_days?: (number | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        iteration_start_dates?: (Array<string | null> | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        current_iteration?: (number | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        current_iteration_start_date?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        response_sampling_start_date?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        response_sampling_interval_type?:
            | (SurveySamplingIntervalTypeEnum | BlankEnum | NullEnum)
            | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        response_sampling_interval?: (number | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        response_sampling_limit?: (number | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        response_sampling_daily_limits?: unknown | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        enable_partial_responses?: (boolean | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        enable_iframe_embedding?: (boolean | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        base_language?: string | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        translations?: unknown | undefined;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        form_content?: unknown | undefined;
        /**
         * How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.
         */
        search_match_type: SearchMatchTypeEnum | NullEnum;
    };
    /**
     * * `next_question` - next_question
     */
    export type SurveyNextQuestionBranchingTypeEnum = "next_question";
    export type SurveyNextQuestionBranching = {
        /**
         * Continue to the next question in sequence.
         *
         * * `next_question` - next_question
         */
        type: SurveyNextQuestionBranchingTypeEnum;
    };
    /**
     * * `end` - end
     */
    export type SurveyEndBranchingTypeEnum = "end";
    export type SurveyEndBranching = {
        /**
         * End the survey.
         *
         * * `end` - end
         */
        type: SurveyEndBranchingTypeEnum;
    };
    /**
     * * `specific_question` - specific_question
     */
    export type SurveySpecificQuestionBranchingTypeEnum = "specific_question";
    export type SurveySpecificQuestionBranching = {
        /**
         * Jump to a specific question index.
         *
         * * `specific_question` - specific_question
         */
        type: SurveySpecificQuestionBranchingTypeEnum;
        /**
         * 0-based index of the next question.
         */
        index: number;
    };
    /**
     * * `response_based` - response_based
     */
    export type SurveyResponseBasedBranchingTypeEnum = "response_based";
    export type SurveyResponseBasedBranching = {
        /**
         * Branch based on the selected or entered response.
         *
         * * `response_based` - response_based
         */
        type: SurveyResponseBasedBranchingTypeEnum;
        /**
         * Response-based branching map. Values can be a question index or 'end'.
         */
        responseValues: Record<string, number | "end">;
    };
    export type SurveyBranchingSchema =
        | SurveyNextQuestionBranching
        | SurveyEndBranching
        | SurveySpecificQuestionBranching
        | SurveyResponseBasedBranching;
    /**
     * * `link` - link
     */
    export type SurveyLinkQuestionSchemaTypeEnum = "link";
    export type SurveyLinkQuestionSchema = {
        id?: string | undefined;
        type: SurveyLinkQuestionSchemaTypeEnum;
        /**
         * Question text shown to respondents.
         */
        question: string;
        description?: string | undefined;
        descriptionContentType?: DescriptionContentTypeEnum | undefined;
        optional?: boolean | undefined;
        buttonText?: string | undefined;
        /**
         * HTTPS or mailto URL for link questions.
         */
        link: string;
    };
    /**
     * * `multiple_choice` - multiple_choice
     */
    export type SurveyMultipleChoiceQuestionSchemaTypeEnum = "multiple_choice";
    export type SurveyMultipleChoiceQuestionSchema = {
        id?: string | undefined;
        type: SurveyMultipleChoiceQuestionSchemaTypeEnum;
        /**
         * Question text shown to respondents.
         */
        question: string;
        description?: string | undefined;
        descriptionContentType?: DescriptionContentTypeEnum | undefined;
        optional?: boolean | undefined;
        buttonText?: string | undefined;
        /**
         * Array of choice options. Multiple selections allowed. No branching logic supported.
         */
        choices: Array<string>;
        shuffleOptions?: boolean | undefined;
        hasOpenChoice?: boolean | undefined;
    };
    /**
     * * `open` - open
     */
    export type SurveyOpenQuestionSchemaTypeEnum = "open";
    export type SurveyOpenQuestionSchema = {
        id?: string | undefined;
        type: SurveyOpenQuestionSchemaTypeEnum;
        /**
         * Question text shown to respondents.
         */
        question: string;
        description?: string | undefined;
        descriptionContentType?: DescriptionContentTypeEnum | undefined;
        optional?: boolean | undefined;
        buttonText?: string | undefined;
    };
    /**
     * * `rating` - rating
     */
    export type SurveyRatingQuestionSchemaTypeEnum = "rating";
    /**
     * * `number` - number
     * * `emoji` - emoji
     */
    export type SurveyRatingQuestionSchemaDisplayEnum = "number" | "emoji";
    export type SurveyRatingQuestionSchema = {
        id?: string | undefined;
        type: SurveyRatingQuestionSchemaTypeEnum;
        /**
         * Question text shown to respondents.
         */
        question: string;
        description?: string | undefined;
        descriptionContentType?: DescriptionContentTypeEnum | undefined;
        optional?: boolean | undefined;
        buttonText?: string | undefined;
        display?: SurveyRatingQuestionSchemaDisplayEnum | undefined;
        scale?: number | undefined;
        lowerBoundLabel?: string | undefined;
        upperBoundLabel?: string | undefined;
        branching?: (SurveyBranchingSchema | null) | undefined;
    };
    /**
     * * `single_choice` - single_choice
     */
    export type SurveySingleChoiceQuestionSchemaTypeEnum = "single_choice";
    export type SurveySingleChoiceQuestionSchema = {
        id?: string | undefined;
        type: SurveySingleChoiceQuestionSchemaTypeEnum;
        /**
         * Question text shown to respondents.
         */
        question: string;
        description?: string | undefined;
        descriptionContentType?: DescriptionContentTypeEnum | undefined;
        optional?: boolean | undefined;
        buttonText?: string | undefined;
        /**
         * Array of choice options. Choice indices (0, 1, 2, ...) are used for branching logic.
         */
        choices: Array<string>;
        shuffleOptions?: boolean | undefined;
        hasOpenChoice?: boolean | undefined;
        branching?: (SurveyBranchingSchema | null) | undefined;
    };
    export type SurveyQuestionInputSchema =
        | SurveyOpenQuestionSchema
        | SurveyLinkQuestionSchema
        | SurveyRatingQuestionSchema
        | SurveySingleChoiceQuestionSchema
        | SurveyMultipleChoiceQuestionSchema;
    export type SurveySerializerCreateUpdateOnly = {
        id: string;
        name: string;
        description?: string | undefined;
        type: SurveyTypeEnum;
        schedule?: (string | null) | undefined;
        linked_flag: MinimalFeatureFlag & unknown;
        linked_flag_id?: (number | null) | undefined;
        linked_insight_id?: (number | null) | undefined;
        targeting_flag_id?: number | undefined;
        targeting_flag: MinimalFeatureFlag & unknown;
        internal_targeting_flag: MinimalFeatureFlag & unknown;
        targeting_flag_filters?: unknown | undefined;
        remove_targeting_flag?: (boolean | null) | undefined;
        questions?: unknown | undefined;
        conditions?: unknown | undefined;
        appearance?: unknown | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        start_date?: (string | null) | undefined;
        end_date?: (string | null) | undefined;
        archived?: boolean | undefined;
        responses_limit?: (number | null) | undefined;
        iteration_count?: (number | null) | undefined;
        iteration_frequency_days?: (number | null) | undefined;
        iteration_start_dates?: (Array<string | null> | null) | undefined;
        current_iteration?: (number | null) | undefined;
        current_iteration_start_date?: (string | null) | undefined;
        response_sampling_start_date?: (string | null) | undefined;
        response_sampling_interval_type?:
            | (SurveySamplingIntervalTypeEnum | BlankEnum | NullEnum)
            | undefined;
        response_sampling_interval?: (number | null) | undefined;
        response_sampling_limit?: (number | null) | undefined;
        response_sampling_daily_limits?: unknown | undefined;
        enable_partial_responses?: (boolean | null) | undefined;
        enable_iframe_embedding?: (boolean | null) | undefined;
        base_language?: string | undefined;
        translations?: unknown | undefined;
        _create_in_folder?: string | undefined;
        form_content?: unknown | undefined;
    };
    export type SurveySerializerCreateUpdateOnlySchema = {
        id: string;
        /**
         * Survey name. Anyone can read it. In-app surveys send it to every visitor's browser alongside the questions and appearance text, and a hosted survey shows it on its public page. Keep customer names and other private details out of it.
         */
        name: string;
        description?: string | undefined;
        /**
         * Survey type.
         *
         * * `popover` - popover
         * * `widget` - widget
         * * `external_survey` - external survey
         * * `api` - api
         */
        type: SurveyTypeEnum;
        schedule?: (SurveyScheduleEnum | NullEnum) | undefined;
        linked_flag: MinimalFeatureFlag & unknown;
        linked_flag_id?: (number | null) | undefined;
        linked_insight_id?: (number | null) | undefined;
        targeting_flag_id?: number | undefined;
        targeting_flag: MinimalFeatureFlag & unknown;
        internal_targeting_flag: MinimalFeatureFlag & unknown;
        targeting_flag_filters?: (FeatureFlagFiltersSchema | null) | undefined;
        remove_targeting_flag?: (boolean | null) | undefined;
        questions?: (Array<SurveyQuestionInputSchema> | null) | undefined;
        conditions?: (SurveyConditionsSchema | null) | undefined;
        appearance?: (SurveyAppearanceSchema | null) | undefined;
        created_at: string;
        created_by: UserBasic & unknown;
        start_date?: (string | null) | undefined;
        end_date?: (string | null) | undefined;
        archived?: boolean | undefined;
        responses_limit?: (number | null) | undefined;
        iteration_count?: (number | null) | undefined;
        iteration_frequency_days?: (number | null) | undefined;
        iteration_start_dates?: (Array<string | null> | null) | undefined;
        current_iteration?: (number | null) | undefined;
        current_iteration_start_date?: (string | null) | undefined;
        response_sampling_start_date?: (string | null) | undefined;
        response_sampling_interval_type?:
            | (SurveySamplingIntervalTypeEnum | BlankEnum | NullEnum)
            | undefined;
        response_sampling_interval?: (number | null) | undefined;
        response_sampling_limit?: (number | null) | undefined;
        response_sampling_daily_limits?: unknown | undefined;
        enable_partial_responses?: (boolean | null) | undefined;
        enable_iframe_embedding?: (boolean | null) | undefined;
        base_language?: string | undefined;
        translations?: unknown | undefined;
        _create_in_folder?: string | undefined;
        form_content?: unknown | undefined;
    };
    export type SurveyStatsResponse = {
        /**
         * The survey ID these stats belong to.
         */
        survey_id: string;
        /**
         * When the survey started collecting responses.
         */
        start_date: string | null;
        /**
         * When the survey stopped collecting responses.
         */
        end_date: string | null;
        /**
         * Event counts keyed by event name (survey shown, survey dismissed, survey sent).
         */
        stats: Record<string, unknown>;
        /**
         * Calculated response and dismissal rates.
         */
        rates: Record<string, unknown>;
        per_question_stats?: Array<unknown> | undefined;
    };
    /**
     * Request body for creating or updating a task.
     *
     * Field required/default semantics match the ``Task`` model. The view passes
     * ``validated_data`` (integration/report PK fields already resolved to instances) to the
     * facade ``create_task`` / ``update_task`` functions.
     */
    export type TaskCreate = Partial<{
        title: string;
        title_manually_set: boolean;
        description: string;
        origin_product: TaskOriginProductEnum;
        repository: string | null;
        repositories: Array<string>;
        github_integration: number | null;
        github_user_integration: string | null;
        signal_report: string | null;
        signal_report_task_relationship: string;
        json_schema: unknown;
        archived: boolean;
        ci_prompt: string | null;
        branch: string | null;
        runtime_adapter: RuntimeAdapterEnum | NullEnum;
        model: string | null;
        reasoning_effort: ReasoningEffortEnum | NullEnum;
        initial_permission_mode:
            | TaskRunBootstrapCreateRequestInitialPermissionModeEnum
            | NullEnum;
        pending_user_message: string | null;
        pending_user_artifact_ids: Array<string>;
        auto_publish: boolean | null;
        channel: string | null;
        naming_source: string;
        sandbox_environment_id: string | null;
        custom_image_id: string | null;
        runtime: TaskRuntimeEnum;
    }>;
    export type TaskRunAnalyzeResponse = {
        /**
         * Id of the analysis task to navigate to.
         */
        analysis_task_id: string;
        /**
         * True when a new analysis task was created; false when an existing analysis for this run was returned.
         */
        created: boolean;
    };
    export type TaskRunResumeRequestSchema = Partial<{
        mode: TaskExecutionModeEnum & unknown;
        branch: string | null;
        resume_from_run_id: string;
        pending_user_message: string;
        sandbox_environment_id: string;
        custom_image_id: string;
        pr_authorship_mode: PrAuthorshipModeEnum;
        run_source: RunSourceEnum;
        signal_report_id: string;
        github_user_token: string;
    }>;
    export type TaskRunCreateRequestSchema =
        | ClaudeTaskRunCreateSchema
        | CodexTaskRunCreateSchema
        | TaskRunResumeRequestSchema;
    export type TaskRunErrorResponse = Partial<{
        detail: string;
        error: string;
        type: string;
        code: string;
        reason: DesktopAccessReasonEnum;
        attr: string;
        missing_artifact_ids: Array<string>;
        limit_type: LimitTypeEnum;
        reset_at: string;
        is_pro: boolean;
    }>;
    export type TaskSummariesRequest = {
        /**
         * Task IDs to fetch summaries for (max 5000). Response is paginated; follow the `next` cursor to retrieve all results.
         */
        ids: Array<string>;
    };
    /**
     * Request body for creating or updating a task.
     *
     * Field required/default semantics match the ``Task`` model. The view passes
     * ``validated_data`` (integration/report PK fields already resolved to instances) to the
     * facade ``create_task`` / ``update_task`` functions.
     */
    export type TaskWrite = Partial<{
        title: string;
        title_manually_set: boolean;
        description: string;
        origin_product: TaskOriginProductEnum;
        repository: string | null;
        repositories: Array<string>;
        github_integration: number | null;
        github_user_integration: string | null;
        signal_report: string | null;
        signal_report_task_relationship: string;
        json_schema: unknown;
        archived: boolean;
        ci_prompt: string | null;
        branch: string | null;
        runtime_adapter: RuntimeAdapterEnum | NullEnum;
        model: string | null;
        reasoning_effort: ReasoningEffortEnum | NullEnum;
        initial_permission_mode:
            | TaskRunBootstrapCreateRequestInitialPermissionModeEnum
            | NullEnum;
        pending_user_message: string | null;
        pending_user_artifact_ids: Array<string>;
        auto_publish: boolean | null;
        channel: string | null;
    }>;
    /**
     * * `0` - Sunday
     * * `1` - Monday
     */
    export type WeekStartDayEnum = 0 | 1;
    export type TeamRevenueAnalyticsConfig = Partial<{
        base_currency: BaseCurrencyEnum;
        events: unknown;
        filter_test_accounts: boolean;
    }>;
    export type TeamMarketingAnalyticsConfig = Partial<{
        sources_map: MarketingAnalyticsSourceMapping;
        conversion_goals: MarketingAnalyticsConversionGoalList;
        attribution_window_days: number;
        attribution_mode: AttributionModeEnum;
        campaign_name_mappings: MarketingAnalyticsCampaignNameMappings;
        custom_source_mappings: MarketingAnalyticsCustomSourceMappings;
        campaign_field_preferences: MarketingAnalyticsCampaignFieldPreferences;
    }>;
    export type TeamCustomerAnalyticsConfig = Partial<{
        activity_event: unknown;
        signup_pageview_event: unknown;
        signup_event: unknown;
        subscription_event: unknown;
        payment_event: unknown;
        account_group_type_index: number | null;
    }>;
    export type TeamWorkflowsConfig = Partial<{
        capture_workflows_engagement_events: boolean;
        email_tracking_consent_mode: EmailTrackingConsentModeEnum;
    }>;
    export type Team = {
        id: number;
        uuid: string;
        name?: string | undefined;
        access_control?: boolean | undefined;
        organization: string;
        project_id: number;
        api_token: string;
        secret_api_token: string | null;
        secret_api_token_backup: string | null;
        created_at: string;
        updated_at: string;
        ingested_event: boolean;
        default_modifiers: Record<string, unknown>;
        person_on_events_querying_enabled: boolean;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
        app_urls?: Array<string | null> | undefined;
        anonymize_ips?: boolean | undefined;
        completed_snippet_onboarding?: boolean | undefined;
        test_account_filters?: unknown | undefined;
        test_account_filters_default_checked?: (boolean | null) | undefined;
        path_cleaning_filters?: unknown | undefined;
        is_demo?: boolean | undefined;
        timezone?: TimezoneEnum | undefined;
        data_attributes?: unknown | undefined;
        person_display_name_properties?: (Array<string> | null) | undefined;
        correlation_config?: unknown | undefined;
        autocapture_opt_out?: (boolean | null) | undefined;
        autocapture_exceptions_opt_in?: (boolean | null) | undefined;
        autocapture_web_vitals_opt_in?: (boolean | null) | undefined;
        autocapture_web_vitals_allowed_metrics?: unknown | undefined;
        autocapture_exceptions_errors_to_ignore?: unknown | undefined;
        capture_console_log_opt_in?: (boolean | null) | undefined;
        logs_settings?: unknown | undefined;
        capture_performance_opt_in?: (boolean | null) | undefined;
        session_recording_opt_in?: boolean | undefined;
        session_recording_sample_rate?: (string | null) | undefined;
        session_recording_minimum_duration_milliseconds?:
            | (number | null)
            | undefined;
        session_recording_linked_flag?: unknown | undefined;
        session_recording_network_payload_capture_config?: unknown | undefined;
        session_recording_masking_config?: unknown | undefined;
        session_recording_url_trigger_config?:
            | (Array<unknown> | null)
            | undefined;
        session_recording_url_blocklist_config?:
            | (Array<unknown> | null)
            | undefined;
        session_recording_event_trigger_config?:
            | (Array<string | null> | null)
            | undefined;
        session_recording_trigger_match_type_config?:
            | (string | null)
            | undefined;
        session_recording_trigger_groups?: unknown | undefined;
        session_recording_retention_period?:
            | SessionRecordingRetentionPeriodEnum
            | undefined;
        session_replay_config?: unknown | undefined;
        survey_config?: unknown | undefined;
        week_start_day?: (WeekStartDayEnum | NullEnum) | undefined;
        primary_dashboard?: (number | null) | undefined;
        live_events_columns?: (Array<string> | null) | undefined;
        recording_domains?: (Array<string | null> | null) | undefined;
        cookieless_server_hash_mode?:
            | (CookielessServerHashModeEnum | NullEnum)
            | undefined;
        human_friendly_comparison_periods?: (boolean | null) | undefined;
        inject_web_apps?: (boolean | null) | undefined;
        extra_settings?: unknown | undefined;
        modifiers?: unknown | undefined;
        has_completed_onboarding_for?: unknown | undefined;
        surveys_opt_in?: (boolean | null) | undefined;
        heatmaps_opt_in?: (boolean | null) | undefined;
        flags_persistence_default?: (boolean | null) | undefined;
        feature_flag_confirmation_enabled?: (boolean | null) | undefined;
        feature_flag_confirmation_message?: (string | null) | undefined;
        default_evaluation_contexts_enabled?: (boolean | null) | undefined;
        require_evaluation_contexts?: (boolean | null) | undefined;
        capture_dead_clicks?: (boolean | null) | undefined;
        default_data_theme?: (number | null) | undefined;
        revenue_analytics_config?: TeamRevenueAnalyticsConfig | undefined;
        marketing_analytics_config?: TeamMarketingAnalyticsConfig | undefined;
        customer_analytics_config?: TeamCustomerAnalyticsConfig | undefined;
        onboarding_tasks?: unknown | undefined;
        base_currency?: (BaseCurrencyEnum & unknown) | undefined;
        web_analytics_pre_aggregated_tables_enabled?:
            | (boolean | null)
            | undefined;
        receive_org_level_activity_logs?: (boolean | null) | undefined;
        business_model?: (BusinessModelEnum | BlankEnum | NullEnum) | undefined;
        conversations_enabled?: (boolean | null) | undefined;
        conversations_settings?: unknown | undefined;
        proactive_tasks_enabled?: (boolean | null) | undefined;
        workflows_config?: TeamWorkflowsConfig | undefined;
        effective_membership_level: OrganizationMembershipLevelEnum & unknown;
        has_group_types: boolean;
        group_types: Array<Record<string, unknown>>;
        live_events_token: string | null;
        product_intents: Array<Record<string, unknown>>;
        managed_viewsets: Record<string, boolean>;
        available_setup_task_ids: Array<AvailableSetupTaskIdsEnum>;
        /**
         * The team's events data retention window in months (plan-derived, synced from billing). When retention enforcement is active for the team, queries do not return events older than this many months. Read-only: this value follows your plan's data retention entitlement, so neither you nor PostHog support can change it unless your organization is on the enterprise plan. Background and discussion: https://github.com/PostHog/posthog/issues/17031
         */
        event_retention_months: number;
        /**
         * Whether events data retention is currently enforced for this team (cohort/flag gated). Read-only: neither you nor PostHog support can turn enforcement off, and the retention window itself only changes with your plan. Background and discussion: https://github.com/PostHog/posthog/issues/17031
         */
        events_retention_enforced: boolean;
    };
    /**
     * Serializer for ticket assignment (user or role).
     */
    export type TicketAssignment = {
        id: string | null;
        type: string;
        user: Record<string, string> | null;
        role: Record<string, string> | null;
    };
    /**
     * Minimal person serializer for embedding in ticket responses.
     */
    export type TicketPerson = {
        id: string;
        name: string;
        distinct_ids: Array<string>;
        properties: Record<string, unknown>;
        created_at: string;
        is_identified: boolean;
    };
    /**
     * Mixin for serializers to add user access control fields
     */
    export type Ticket = {
        id: string;
        ticket_number: number;
        channel_source: ChannelEnum & unknown;
        channel_detail: ChannelDetailEnum | NullEnum;
        distinct_id: string;
        /**
         * Mixin for serializers to add user access control fields
         */
        status?: TicketStatusEnum | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        priority?: (TicketPriorityEnum | BlankEnum | NullEnum) | undefined;
        assignee: TicketAssignment & unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        anonymous_traits?: unknown | undefined;
        /**
         * Trust signal indicating whether the ticket's claimed identity was attested by the server (widget HMAC, SPF-authenticated email, or a signature-validated platform webhook). True when verified, false when assessed but not attested, null when unknown (e.g. created before this signal existed).
         */
        identity_verified: boolean | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        ai_resolved?: boolean | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        escalation_reason?: (string | null) | undefined;
        /**
         * AI support pipeline triage and outcome (status, result, ticket_type, confidence, attempts, etc.).
         */
        ai_triage: unknown;
        created_at: string;
        updated_at: string;
        message_count: number;
        last_message_at: string | null;
        last_message_text: string | null;
        unread_team_count: number;
        unread_customer_count: number;
        session_id: string | null;
        session_context: unknown;
        /**
         * Mixin for serializers to add user access control fields
         */
        sla_due_at?: (string | null) | undefined;
        /**
         * Mixin for serializers to add user access control fields
         */
        snoozed_until?: (string | null) | undefined;
        slack_channel_id: string | null;
        slack_thread_ts: string | null;
        slack_team_id: string | null;
        email_subject: string | null;
        email_from: string | null;
        email_to: string | null;
        cc_participants: unknown;
        github_repo: string | null;
        github_issue_number: number | null;
        zendesk_ticket_id: number | null;
        /**
         * Customer's PostHog organization group key, resolved at ticket creation. Null when unknown.
         */
        organization_id: string | null;
        /**
         * How organization_id was resolved: 'person' (from the requester's identity) or 'slack_channel_account' (inferred from the customer analytics account linked to the ticket's Slack channel). Null when organization_id is unset.
         */
        organization_id_source: string | null;
        person: TicketPerson | null;
        /**
         * Mixin for serializers to add user access control fields
         */
        tags?: Array<unknown> | undefined;
        /**
         * The effective access level the user has for this object
         */
        user_access_level: string | null;
    };
    /**
     * Fields accepted when updating a ticket.
     */
    export type TicketUpdateRequest = Partial<{
        status: TicketStatusEnum;
        priority: TicketPriorityEnum | BlankEnum | NullEnum;
        assignee: TicketAssigneeRequest | null;
        anonymous_traits: unknown;
        ai_resolved: boolean;
        escalation_reason: string | null;
        sla_due_at: string | null;
        snoozed_until: string | null;
        tags: Array<string>;
    }>;
    export type UserGithubLogin = {
        /**
         * The user's resolved GitHub login, or null when no GitHub identity is linked.
         */
        github_login: string | null;
    };
    export type _DateRange = Partial<{
        date_from: string | null;
        date_to: string | null;
    }>;
    /**
     * * `log` - log
     * * `log_attribute` - log_attribute
     * * `log_resource_attribute` - log_resource_attribute
     */
    export type _LogPropertyFilterTypeEnum =
        | "log"
        | "log_attribute"
        | "log_resource_attribute";
    /**
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `starts_with` - starts_with
     * * `not_starts_with` - not_starts_with
     * * `ends_with` - ends_with
     * * `not_ends_with` - not_ends_with
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `lt` - lt
     * * `is_date_exact` - is_date_exact
     * * `is_date_before` - is_date_before
     * * `is_date_after` - is_date_after
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set
     */
    export type _LogPropertyFilterOperatorEnum =
        | "exact"
        | "is_not"
        | "icontains"
        | "not_icontains"
        | "starts_with"
        | "not_starts_with"
        | "ends_with"
        | "not_ends_with"
        | "regex"
        | "not_regex"
        | "gt"
        | "lt"
        | "is_date_exact"
        | "is_date_before"
        | "is_date_after"
        | "is_set"
        | "is_not_set";
    export type _LogPropertyFilter = {
        /**
         * Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name").
         */
        key: string;
        /**
         * "log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.
         *
         * * `log` - log
         * * `log_attribute` - log_attribute
         * * `log_resource_attribute` - log_resource_attribute
         */
        type: _LogPropertyFilterTypeEnum;
        /**
         * Comparison operator.
         *
         * * `exact` - exact
         * * `is_not` - is_not
         * * `icontains` - icontains
         * * `not_icontains` - not_icontains
         * * `starts_with` - starts_with
         * * `not_starts_with` - not_starts_with
         * * `ends_with` - ends_with
         * * `not_ends_with` - not_ends_with
         * * `regex` - regex
         * * `not_regex` - not_regex
         * * `gt` - gt
         * * `lt` - lt
         * * `is_date_exact` - is_date_exact
         * * `is_date_before` - is_date_before
         * * `is_date_after` - is_date_after
         * * `is_set` - is_set
         * * `is_not_set` - is_not_set
         */
        operator: _LogPropertyFilterOperatorEnum;
        value?: unknown | undefined;
    };

    // </Schemas>
}

export namespace Endpoints {
    // <Endpoints>

    export type get_Actions_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/actions/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.Action };
    };
    export type put_Actions_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/actions/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: number; project_id: string };

            body: Schemas.Action;
        };
        responses: { 200: Schemas.Action };
    };
    export type patch_Actions_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/actions/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: number; project_id: string };

            body: Schemas.PatchedAction;
        };
        responses: { 200: Schemas.Action };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Actions_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/actions/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: number; project_id: string };
        };
        responses: { 405: unknown };
    };
    export type get_Cohorts_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/cohorts/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.Cohort };
    };
    export type put_Cohorts_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/cohorts/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };

            body: Schemas.Cohort;
        };
        responses: { 200: Schemas.Cohort };
    };
    export type patch_Cohorts_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/cohorts/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };

            body: Schemas.PatchedCohort;
        };
        responses: { 200: Schemas.Cohort };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Cohorts_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/cohorts/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 405: unknown };
    };
    export type get_Comments_list = {
        method: "GET";
        path: "/api/projects/{project_id}/comments/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                completed: "any" | "open" | "completed";
                cursor: string;
                item_id: string;
                kind: "any" | "comment" | "task";
                scope: string;
                search: string;
                source_comment: string;
                task_id: string;
            }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedCommentList };
    };
    /**
     * Create a comment.
     *
     * Support messages are deduplicated: an identical message from the same author on the same
     * ticket within a short window returns the original comment with a 200 instead of creating a
     * second one, and a 409 while a concurrent request is still creating it.
     */
    export type post_Comments_create = {
        method: "POST";
        path: "/api/projects/{project_id}/comments/";
        requestFormat: "json";
        parameters: {
            path: { project_id: string };

            body: Schemas.Comment;
        };
        responses: {
            200: Schemas.Comment;
            201: Schemas.Comment;
            409: Schemas.CommentError;
        };
    };
    /**
     * Get single ticket and mark as read by team.
     */
    export type get_Conversations_tickets_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/conversations/tickets/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.Ticket };
    };
    /**
     * Handle ticket updates including assignee changes.
     */
    export type put_Conversations_tickets_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/conversations/tickets/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.TicketUpdateRequest;
        };
        responses: { 200: Schemas.Ticket };
    };
    export type patch_Conversations_tickets_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/conversations/tickets/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedTicketUpdateRequest;
        };
        responses: { 200: Schemas.Ticket };
    };
    export type delete_Conversations_tickets_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/conversations/tickets/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 204: unknown };
    };
    export type get_Dashboards_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/dashboards/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                filters_override: string;
                format: "json" | "txt";
                include_dashboards: boolean;
                variables_override: string;
            }>;
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.Dashboard };
    };
    export type put_Dashboards_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/dashboards/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                format: "json" | "txt";
                include_dashboards: boolean;
            }>;
            path: { id: number; project_id: string };

            body: Schemas.Dashboard;
        };
        responses: { 200: Schemas.Dashboard };
    };
    export type patch_Dashboards_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/dashboards/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                format: "json" | "txt";
                include_dashboards: boolean;
            }>;
            path: { id: number; project_id: string };

            body: Schemas.PatchedPatchedDashboardOpenApi;
        };
        responses: { 200: Schemas.Dashboard };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Dashboards_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/dashboards/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "json" | "txt" }>;
            path: { id: number; project_id: string };
        };
        responses: { 405: unknown };
    };
    export type get_Error_tracking_issues_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/error_tracking/issues/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.ErrorTrackingIssueRead };
    };
    export type put_Error_tracking_issues_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/error_tracking/issues/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.ErrorTrackingIssueWrite;
        };
        responses: { 200: Schemas.ErrorTrackingIssueRead };
    };
    export type patch_Error_tracking_issues_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/error_tracking/issues/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedErrorTrackingIssueWrite;
        };
        responses: { 200: Schemas.ErrorTrackingIssueRead };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Error_tracking_issues_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/error_tracking/issues/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 405: unknown };
    };
    export type get_Evaluations_list = {
        method: "GET";
        path: "/api/projects/{project_id}/evaluations/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                directory_id: string;
                directory_id__isnull: boolean;
                enabled: boolean;
                evaluation_type: "hog" | "llm_judge" | "sentiment";
                id__in: Array<string>;
                limit: number;
                offset: number;
                order_by: Array<
                    | "-created_at"
                    | "-name"
                    | "-updated_at"
                    | "created_at"
                    | "name"
                    | "updated_at"
                >;
                search: string;
            }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedEvaluationList };
    };
    export type post_Evaluations_create = {
        method: "POST";
        path: "/api/projects/{project_id}/evaluations/";
        requestFormat: "json";
        parameters: {
            path: { project_id: string };

            body: Schemas.Evaluation;
        };
        responses: { 201: Schemas.Evaluation };
    };
    export type get_Evaluations_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/evaluations/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.Evaluation };
    };
    export type put_Evaluations_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/evaluations/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.Evaluation;
        };
        responses: { 200: Schemas.Evaluation };
    };
    export type patch_Evaluations_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/evaluations/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedEvaluation;
        };
        responses: { 200: Schemas.Evaluation };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Evaluations_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/evaluations/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 405: unknown };
    };
    /**
     * Get event definition by exact name
     */
    export type get_Event_definitions_by_name_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/event_definitions/by_name/";
        requestFormat: "json";
        parameters: {
            query: { name: string };
            path: { project_id: string };
        };
        responses: { 200: Schemas.EventDefinitionRecord };
    };
    /**
     * Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.
     */
    export type get_Experiments_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/experiments/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.Experiment };
    };
    /**
     * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
     *
     * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
     * decorator on serializer methods and converts them into the same responses the viewset path
     * produces (see decorators._result_to_response), so both paths share one contract.
     */
    export type put_Experiments_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/experiments/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };

            body: Schemas.ExperimentWrite;
        };
        responses: { 200: Schemas.Experiment };
    };
    /**
     * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time. Feature-flag config (variants, rollout, payloads) is sent via the feature_flag object.
     */
    export type patch_Experiments_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/experiments/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };

            body: Schemas.PatchedExperimentWrite;
        };
        responses: { 200: Schemas.Experiment };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Experiments_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/experiments/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 405: unknown };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type get_External_data_sources_list = {
        method: "GET";
        path: "/api/projects/{project_id}/external_data_sources/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedExternalDataSourceSerializersList };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type post_External_data_sources_create = {
        method: "POST";
        path: "/api/projects/{project_id}/external_data_sources/";
        requestFormat: "json";
        parameters: {
            path: { project_id: string };

            body: Schemas.ExternalDataSourceCreate;
        };
        responses: { 201: Schemas.ExternalDataSourceCreateResponse };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type get_External_data_sources_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/external_data_sources/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.ExternalDataSourceSerializers };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type put_External_data_sources_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/external_data_sources/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.ExternalDataSourceSerializers;
        };
        responses: { 200: Schemas.ExternalDataSourceSerializers };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type patch_External_data_sources_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/external_data_sources/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedExternalDataSourceSerializers;
        };
        responses: { 200: Schemas.ExternalDataSourceSerializers };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type delete_External_data_sources_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/external_data_sources/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 204: unknown };
    };
    /**
     * Create, Read, Update and Delete External data Sources.
     */
    export type patch_External_data_sources_bulk_update_schemas_partial_update =
        {
            method: "PATCH";
            path: "/api/projects/{project_id}/external_data_sources/{id}/bulk_update_schemas/";
            requestFormat: "json";
            parameters: {
                query: Partial<{
                    limit: number;
                    offset: number;
                    search: string;
                }>;
                path: { id: string; project_id: string };

                body: Schemas.PatchedExternalDataSourceBulkUpdateSchemas;
            };
            responses: { 200: Schemas.PaginatedExternalDataSchemaList };
        };
    /**
     * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
     *
     * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
     */
    export type get_Feature_flags_list = {
        method: "GET";
        path: "/api/projects/{project_id}/feature_flags/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                active: "STALE" | "false" | "true";
                archived: "false" | "true";
                created_by_id: string;
                eligible_for_experiment: "true";
                evaluation_runtime: "all" | "client" | "server";
                excluded_properties: string;
                excluded_tags: string;
                has_evaluation_contexts: "false" | "true";
                key: string;
                limit: number;
                offset: number;
                search: string;
                tags: string;
                type:
                    | "boolean"
                    | "experiment"
                    | "multivariant"
                    | "remote_config";
            }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedFeatureFlagList };
    };
    /**
     * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
     *
     * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
     */
    export type post_Feature_flags_create = {
        method: "POST";
        path: "/api/projects/{project_id}/feature_flags/";
        requestFormat: "json";
        parameters: {
            path: { project_id: string };

            body: Schemas.FeatureFlagCreateRequestSchema;
        };
        responses: { 201: Schemas.FeatureFlag };
    };
    /**
     * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
     *
     * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
     */
    export type get_Feature_flags_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/feature_flags/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.FeatureFlag };
    };
    /**
     * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
     *
     * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
     */
    export type put_Feature_flags_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/feature_flags/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };

            body: Schemas.FeatureFlag;
        };
        responses: { 200: Schemas.FeatureFlag };
    };
    /**
     * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
     *
     * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
     */
    export type patch_Feature_flags_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/feature_flags/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };

            body: Schemas.PatchedFeatureFlagPartialUpdateRequestSchema;
        };
        responses: { 200: Schemas.FeatureFlag };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Feature_flags_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/feature_flags/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 405: unknown };
    };
    /**
     * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.
     *
     * If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
     */
    export type get_Feature_flags_status_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/feature_flags/{id}/status/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.FeatureFlagStatusResponse };
    };
    export type get_Hog_flows_list = {
        method: "GET";
        path: "/api/projects/{project_id}/hog_flows/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                created_at: string;
                created_by: string;
                id: string;
                limit: number;
                offset: number;
                origin_product: "loops";
                search: string;
                status: "active" | "archived" | "draft";
                trigger: string;
                type: "automation" | "messaging";
                updated_at: string;
            }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedHogFlowMinimalList };
    };
    export type post_Hog_flows_create = {
        method: "POST";
        path: "/api/projects/{project_id}/hog_flows/";
        requestFormat: "json";
        parameters: {
            path: { project_id: string };

            body: Schemas.HogFlow;
        };
        responses: { 201: Schemas.HogFlow };
    };
    export type get_Hog_flows_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/hog_flows/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.HogFlow };
    };
    export type put_Hog_flows_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/hog_flows/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.HogFlowUpdate;
        };
        responses: { 200: Schemas.HogFlowUpdate };
    };
    export type patch_Hog_flows_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/hog_flows/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedHogFlowUpdate;
        };
        responses: { 200: Schemas.HogFlowUpdate };
    };
    export type delete_Hog_flows_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/hog_flows/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 204: unknown };
    };
    /**
     * Fire a schedule-triggered workflow immediately, outside its regular schedule.
     *
     * Restricted to the `schedule` trigger type: `batch`/`webhook`/etc. triggers have their own
     * dedicated entry points (`batch_jobs`, the public webhook URL) with trigger-specific
     * guardrails this endpoint doesn't replicate. Requires the workflow to be active, same gate
     * the scheduler itself applies in `internal_process_due_schedules`.
     *
     * Send an `Idempotency-Key` header to dedupe retries (a double-click, or a client retry
     * after a timed-out request): a repeat with the same key returns the first call's result
     * instead of firing a second AI task. Without the header, every call fires a new run.
     */
    export type post_Hog_flows_run_create = {
        method: "POST";
        path: "/api/projects/{project_id}/hog_flows/{id}/run/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.HogFlowRunRequest;
        };
        responses: { 200: Schemas.HogFlowRunResponse; 409: unknown };
    };
    export type get_Hog_flows_schedules_list = {
        method: "GET";
        path: "/api/projects/{project_id}/hog_flows/{id}/schedules/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Array<Schemas.HogFlowSchedule> };
    };
    export type post_Hog_flows_schedules_create = {
        method: "POST";
        path: "/api/projects/{project_id}/hog_flows/{id}/schedules/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.HogFlowSchedule;
        };
        responses: { 200: Schemas.HogFlowSchedule };
    };
    export type patch_Hog_flows_schedules_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/hog_flows/{id}/schedules/{schedule_id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string; schedule_id: string };

            body: Schemas.PatchedHogFlowSchedule;
        };
        responses: { 200: Schemas.HogFlowSchedule };
    };
    export type delete_Hog_flows_schedules_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/hog_flows/{id}/schedules/{schedule_id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string; schedule_id: string };
        };
        responses: { 204: unknown };
    };
    /**
     * DRF ViewSet mixin that gates coalesced responses behind permission checks.
     *
     * The QueryCoalescingMiddleware attaches cached response data to
     * request.META["_coalesced_response"] for followers. This mixin runs DRF's
     * initial() (auth + permissions + throttling) before returning the
     * cached response, ensuring the request is authorized.
     */
    export type get_Insights_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/insights/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                filters_override: string;
                format: "csv" | "json";
                from_dashboard: number;
                include_dashboards: boolean;
                refresh:
                    | "async"
                    | "async_except_on_cache_miss"
                    | "blocking"
                    | "force_async"
                    | "force_blocking"
                    | "force_cache"
                    | "lazy_async";
                variables_override: string;
            }>;
            path: { id: number | string; project_id: string };
        };
        responses: { 200: Schemas.Insight };
    };
    /**
     * DRF ViewSet mixin that gates coalesced responses behind permission checks.
     *
     * The QueryCoalescingMiddleware attaches cached response data to
     * request.META["_coalesced_response"] for followers. This mixin runs DRF's
     * initial() (auth + permissions + throttling) before returning the
     * cached response, ensuring the request is authorized.
     */
    export type put_Insights_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/insights/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                format: "csv" | "json";
                include_dashboards: boolean;
            }>;
            path: { id: number | string; project_id: string };

            body: Schemas.Insight;
        };
        responses: { 200: Schemas.Insight };
    };
    /**
     * DRF ViewSet mixin that gates coalesced responses behind permission checks.
     *
     * The QueryCoalescingMiddleware attaches cached response data to
     * request.META["_coalesced_response"] for followers. This mixin runs DRF's
     * initial() (auth + permissions + throttling) before returning the
     * cached response, ensuring the request is authorized.
     */
    export type patch_Insights_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/insights/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                format: "csv" | "json";
                include_dashboards: boolean;
            }>;
            path: { id: number | string; project_id: string };

            body: Schemas.PatchedInsight;
        };
        responses: { 200: Schemas.Insight };
    };
    /**
     * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
     */
    export type delete_Insights_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/insights/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: number | string; project_id: string };
        };
        responses: { 405: unknown };
    };
    export type get_Integrations_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/integrations/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 200: Schemas.IntegrationConfig };
    };
    export type delete_Integrations_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/integrations/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: number; project_id: string };
        };
        responses: { 204: unknown };
    };
    /**
     * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
     */
    export type get_Persons_list = {
        method: "GET";
        path: "/api/projects/{project_id}/persons/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                client_query_id: string;
                distinct_id: string;
                email: string;
                format: "csv" | "json";
                limit: number;
                offset: number;
                properties: Array<Schemas.Property>;
                search: string;
            }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedPersonRecordList };
    };
    /**
     * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
     */
    export type get_Persons_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/persons/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.PersonRecord };
    };
    /**
     * Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
     * This means that only the properties listed will be updated, but other properties won't be removed nor updated.
     * If you would like to remove a property use the `delete_property` endpoint.
     */
    export type put_Persons_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/persons/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: string; project_id: string };

            body: Schemas.PersonRecord;
        };
        responses: { 200: Schemas.PersonRecord };
    };
    /**
     * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
     */
    export type patch_Persons_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/persons/{id}/";
        requestFormat: "json";
        parameters: {
            query: Partial<{ format: "csv" | "json" }>;
            path: { id: string; project_id: string };

            body: Schemas.PatchedPersonRecord;
        };
        responses: { 200: Schemas.PersonRecord };
    };
    export type get_Session_recordings_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/session_recordings/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.SessionRecording };
    };
    export type put_Session_recordings_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/session_recordings/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.SessionRecording;
        };
        responses: { 200: Schemas.SessionRecording };
    };
    export type patch_Session_recordings_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/session_recordings/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedSessionRecording;
        };
        responses: { 200: Schemas.SessionRecording };
    };
    export type delete_Session_recordings_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/session_recordings/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 204: unknown };
    };
    export type get_Surveys_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/surveys/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.Survey };
    };
    export type put_Surveys_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/surveys/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.SurveySerializerCreateUpdateOnlySchema;
        };
        responses: { 200: Schemas.SurveySerializerCreateUpdateOnly };
    };
    export type patch_Surveys_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/surveys/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedSurveySerializerCreateUpdateOnlySchema;
        };
        responses: { 200: Schemas.SurveySerializerCreateUpdateOnly };
    };
    export type delete_Surveys_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/surveys/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 204: unknown };
    };
    /**
     * Get survey response statistics for a specific survey.
     *
     * Args:
     *     date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
     *     date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
     *     exclude_archived: Optional boolean to exclude archived responses (default: false, includes archived)
     *     include_per_question_stats: Optional boolean to include per-question response counts and distributions
     *
     * Returns:
     *     Survey statistics including event counts, unique respondents, and conversion rates
     */
    export type get_Surveys_stats_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/surveys/{id}/stats/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                date_from: string;
                date_to: string;
                include_per_question_stats: boolean;
            }>;
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.SurveyStatsResponse };
    };
    /**
     * Get a list of tasks for the current project, with optional filtering by origin product, stage, organization, repository, created_by, and the workflow (hog_flow_id) that created the task.
     */
    export type get_Tasks_list = {
        method: "GET";
        path: "/api/projects/{project_id}/tasks/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                all_team_tasks: boolean;
                archived: "true" | "false" | "all";
                channel: string;
                ci_status: "passing" | "failing" | "pending" | "none";
                commented_by: number;
                created_by: number;
                exclude_origin_product:
                    | "onboarding"
                    | "error_tracking"
                    | "eval_clusters"
                    | "user_created"
                    | "slack"
                    | "support_queue"
                    | "session_summaries"
                    | "posthog_ai"
                    | "experiments"
                    | "signal_report"
                    | "signals_scout"
                    | "scout_suggestions"
                    | "support_reply"
                    | "hogdesk"
                    | "review_hog"
                    | "image_builder"
                    | "loop"
                    | "mcp_analytics"
                    | "signals_chat"
                    | "task_analysis"
                    | "workflow";
                hog_flow_id: string;
                internal: "true" | "false" | "all";
                limit: number;
                mentions: number;
                offset: number;
                ordering: "-created_at" | "-last_activity_at";
                organization: string;
                origin_product: string;
                pinned: boolean;
                pr_state: "open" | "draft" | "merged" | "closed";
                repository: string;
                search: string;
                stage: string;
                status:
                    | "not_started"
                    | "queued"
                    | "in_progress"
                    | "completed"
                    | "failed"
                    | "cancelled";
            }>;
            path: { project_id: string };
        };
        responses: { 200: Schemas.PaginatedTaskDetailDTOList };
    };
    /**
     * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
     */
    export type post_Tasks_create = {
        method: "POST";
        path: "/api/projects/{project_id}/tasks/";
        requestFormat: "json";
        parameters: {
            path: { project_id: string };

            body: Schemas.TaskCreate;
        };
        responses: {
            201: Schemas.TaskDetailDTO;
            403: Schemas.TaskRunErrorResponse;
            429: Schemas.TaskRunErrorResponse;
            503: Schemas.TaskRunErrorResponse;
        };
    };
    /**
     * Retrieve a single task by ID.
     */
    export type get_Tasks_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/tasks/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 200: Schemas.TaskDetailDTO };
    };
    /**
     * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
     */
    export type put_Tasks_update = {
        method: "PUT";
        path: "/api/projects/{project_id}/tasks/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.TaskWrite;
        };
        responses: { 200: Schemas.TaskDetailDTO };
    };
    /**
     * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
     */
    export type patch_Tasks_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/tasks/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.PatchedTaskWrite;
        };
        responses: { 200: Schemas.TaskDetailDTO };
    };
    /**
     * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
     */
    export type delete_Tasks_destroy = {
        method: "DELETE";
        path: "/api/projects/{project_id}/tasks/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };
        };
        responses: { 204: unknown };
    };
    /**
     * Create a new task run and kick off the workflow.
     */
    export type post_Tasks_run_create = {
        method: "POST";
        path: "/api/projects/{project_id}/tasks/{id}/run/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string };

            body: Schemas.TaskRunCreateRequestSchema;
        };
        responses: {
            200: Schemas.TaskDetailDTO;
            400: Schemas.TaskRunErrorResponse;
            403: Schemas.TaskRunErrorResponse;
            404: unknown;
            429: Schemas.TaskRunErrorResponse;
            503: Schemas.TaskRunErrorResponse;
        };
    };
    /**
     * Retrieve a single run for a specific task.
     */
    export type get_Tasks_runs_retrieve = {
        method: "GET";
        path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string; task_id: string };
        };
        responses: { 200: Schemas.TaskRunDetailDTO; 404: unknown };
    };
    /**
     * API for managing task runs. Each run represents an execution of a task.
     */
    export type patch_Tasks_runs_partial_update = {
        method: "PATCH";
        path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string; task_id: string };

            body: Schemas.PatchedTaskRunUpdate;
        };
        responses: {
            200: Schemas.TaskRunDetailDTO;
            400: Schemas.TaskRunErrorResponse;
            404: unknown;
        };
    };
    /**
     * Create a PostHog-funded analysis task that reviews this run's transcript for inefficiencies and reports findings. Idempotent per run: if an analysis task already exists for this run, it is returned instead of creating another. The analysis is not billed to the customer.
     */
    export type post_Tasks_runs_analyze_create = {
        method: "POST";
        path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/analyze/";
        requestFormat: "json";
        parameters: {
            path: { id: string; project_id: string; task_id: string };
        };
        responses: {
            200: Schemas.TaskRunAnalyzeResponse;
            201: Schemas.TaskRunAnalyzeResponse;
            400: unknown;
            403: unknown;
            404: unknown;
        };
    };
    export type get_Users_list = {
        method: "GET";
        path: "/api/users/";
        requestFormat: "json";
        parameters: {
            query: Partial<{
                email: string;
                is_staff: boolean;
                limit: number;
                offset: number;
            }>;
        };
        responses: { 200: Schemas.PaginatedUserList };
    };
    /**
     * Retrieve a user's profile and settings. Pass `@me` as the UUID to fetch the authenticated user; non-staff callers may only access their own account.
     */
    export type get_Users_retrieve = {
        method: "GET";
        path: "/api/users/{uuid}/";
        requestFormat: "json";
        parameters: {
            path: { uuid: string };
        };
        responses: { 200: Schemas.User };
    };
    /**
     * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
     */
    export type put_Users_update = {
        method: "PUT";
        path: "/api/users/{uuid}/";
        requestFormat: "json";
        parameters: {
            path: { uuid: string };

            body: Schemas.User;
        };
        responses: { 200: Schemas.User };
    };
    /**
     * Update one or more of the authenticated user's profile fields or settings.
     */
    export type patch_Users_partial_update = {
        method: "PATCH";
        path: "/api/users/{uuid}/";
        requestFormat: "json";
        parameters: {
            path: { uuid: string };

            body: Schemas.PatchedUser;
        };
        responses: { 200: Schemas.User };
    };
    export type delete_Users_destroy = {
        method: "DELETE";
        path: "/api/users/{uuid}/";
        requestFormat: "json";
        parameters: {
            path: { uuid: string };
        };
        responses: { 204: unknown };
    };
    export type get_Users_github_login_retrieve = {
        method: "GET";
        path: "/api/users/{uuid}/github_login/";
        requestFormat: "json";
        parameters: {
            path: { uuid: string };
        };
        responses: { 200: Schemas.UserGithubLogin };
    };

    // </Endpoints>
}

// <EndpointByMethod>
export type EndpointByMethod = {
    get: {
        "/api/projects/{project_id}/actions/{id}/": Endpoints.get_Actions_retrieve;
        "/api/projects/{project_id}/cohorts/{id}/": Endpoints.get_Cohorts_retrieve;
        "/api/projects/{project_id}/comments/": Endpoints.get_Comments_list;
        "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.get_Conversations_tickets_retrieve;
        "/api/projects/{project_id}/dashboards/{id}/": Endpoints.get_Dashboards_retrieve;
        "/api/projects/{project_id}/error_tracking/issues/{id}/": Endpoints.get_Error_tracking_issues_retrieve;
        "/api/projects/{project_id}/evaluations/": Endpoints.get_Evaluations_list;
        "/api/projects/{project_id}/evaluations/{id}/": Endpoints.get_Evaluations_retrieve;
        "/api/projects/{project_id}/event_definitions/by_name/": Endpoints.get_Event_definitions_by_name_retrieve;
        "/api/projects/{project_id}/experiments/{id}/": Endpoints.get_Experiments_retrieve;
        "/api/projects/{project_id}/external_data_sources/": Endpoints.get_External_data_sources_list;
        "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.get_External_data_sources_retrieve;
        "/api/projects/{project_id}/feature_flags/": Endpoints.get_Feature_flags_list;
        "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.get_Feature_flags_retrieve;
        "/api/projects/{project_id}/feature_flags/{id}/status/": Endpoints.get_Feature_flags_status_retrieve;
        "/api/projects/{project_id}/hog_flows/": Endpoints.get_Hog_flows_list;
        "/api/projects/{project_id}/hog_flows/{id}/": Endpoints.get_Hog_flows_retrieve;
        "/api/projects/{project_id}/hog_flows/{id}/schedules/": Endpoints.get_Hog_flows_schedules_list;
        "/api/projects/{project_id}/insights/{id}/": Endpoints.get_Insights_retrieve;
        "/api/projects/{project_id}/integrations/{id}/": Endpoints.get_Integrations_retrieve;
        "/api/projects/{project_id}/persons/": Endpoints.get_Persons_list;
        "/api/projects/{project_id}/persons/{id}/": Endpoints.get_Persons_retrieve;
        "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.get_Session_recordings_retrieve;
        "/api/projects/{project_id}/surveys/{id}/": Endpoints.get_Surveys_retrieve;
        "/api/projects/{project_id}/surveys/{id}/stats/": Endpoints.get_Surveys_stats_retrieve;
        "/api/projects/{project_id}/tasks/": Endpoints.get_Tasks_list;
        "/api/projects/{project_id}/tasks/{id}/": Endpoints.get_Tasks_retrieve;
        "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/": Endpoints.get_Tasks_runs_retrieve;
        "/api/users/": Endpoints.get_Users_list;
        "/api/users/{uuid}/": Endpoints.get_Users_retrieve;
        "/api/users/{uuid}/github_login/": Endpoints.get_Users_github_login_retrieve;
    };
    put: {
        "/api/projects/{project_id}/actions/{id}/": Endpoints.put_Actions_update;
        "/api/projects/{project_id}/cohorts/{id}/": Endpoints.put_Cohorts_update;
        "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.put_Conversations_tickets_update;
        "/api/projects/{project_id}/dashboards/{id}/": Endpoints.put_Dashboards_update;
        "/api/projects/{project_id}/error_tracking/issues/{id}/": Endpoints.put_Error_tracking_issues_update;
        "/api/projects/{project_id}/evaluations/{id}/": Endpoints.put_Evaluations_update;
        "/api/projects/{project_id}/experiments/{id}/": Endpoints.put_Experiments_update;
        "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.put_External_data_sources_update;
        "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.put_Feature_flags_update;
        "/api/projects/{project_id}/hog_flows/{id}/": Endpoints.put_Hog_flows_update;
        "/api/projects/{project_id}/insights/{id}/": Endpoints.put_Insights_update;
        "/api/projects/{project_id}/persons/{id}/": Endpoints.put_Persons_update;
        "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.put_Session_recordings_update;
        "/api/projects/{project_id}/surveys/{id}/": Endpoints.put_Surveys_update;
        "/api/projects/{project_id}/tasks/{id}/": Endpoints.put_Tasks_update;
        "/api/users/{uuid}/": Endpoints.put_Users_update;
    };
    patch: {
        "/api/projects/{project_id}/actions/{id}/": Endpoints.patch_Actions_partial_update;
        "/api/projects/{project_id}/cohorts/{id}/": Endpoints.patch_Cohorts_partial_update;
        "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.patch_Conversations_tickets_partial_update;
        "/api/projects/{project_id}/dashboards/{id}/": Endpoints.patch_Dashboards_partial_update;
        "/api/projects/{project_id}/error_tracking/issues/{id}/": Endpoints.patch_Error_tracking_issues_partial_update;
        "/api/projects/{project_id}/evaluations/{id}/": Endpoints.patch_Evaluations_partial_update;
        "/api/projects/{project_id}/experiments/{id}/": Endpoints.patch_Experiments_partial_update;
        "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.patch_External_data_sources_partial_update;
        "/api/projects/{project_id}/external_data_sources/{id}/bulk_update_schemas/": Endpoints.patch_External_data_sources_bulk_update_schemas_partial_update;
        "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.patch_Feature_flags_partial_update;
        "/api/projects/{project_id}/hog_flows/{id}/": Endpoints.patch_Hog_flows_partial_update;
        "/api/projects/{project_id}/hog_flows/{id}/schedules/{schedule_id}/": Endpoints.patch_Hog_flows_schedules_partial_update;
        "/api/projects/{project_id}/insights/{id}/": Endpoints.patch_Insights_partial_update;
        "/api/projects/{project_id}/persons/{id}/": Endpoints.patch_Persons_partial_update;
        "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.patch_Session_recordings_partial_update;
        "/api/projects/{project_id}/surveys/{id}/": Endpoints.patch_Surveys_partial_update;
        "/api/projects/{project_id}/tasks/{id}/": Endpoints.patch_Tasks_partial_update;
        "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/": Endpoints.patch_Tasks_runs_partial_update;
        "/api/users/{uuid}/": Endpoints.patch_Users_partial_update;
    };
    delete: {
        "/api/projects/{project_id}/actions/{id}/": Endpoints.delete_Actions_destroy;
        "/api/projects/{project_id}/cohorts/{id}/": Endpoints.delete_Cohorts_destroy;
        "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.delete_Conversations_tickets_destroy;
        "/api/projects/{project_id}/dashboards/{id}/": Endpoints.delete_Dashboards_destroy;
        "/api/projects/{project_id}/error_tracking/issues/{id}/": Endpoints.delete_Error_tracking_issues_destroy;
        "/api/projects/{project_id}/evaluations/{id}/": Endpoints.delete_Evaluations_destroy;
        "/api/projects/{project_id}/experiments/{id}/": Endpoints.delete_Experiments_destroy;
        "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.delete_External_data_sources_destroy;
        "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.delete_Feature_flags_destroy;
        "/api/projects/{project_id}/hog_flows/{id}/": Endpoints.delete_Hog_flows_destroy;
        "/api/projects/{project_id}/hog_flows/{id}/schedules/{schedule_id}/": Endpoints.delete_Hog_flows_schedules_destroy;
        "/api/projects/{project_id}/insights/{id}/": Endpoints.delete_Insights_destroy;
        "/api/projects/{project_id}/integrations/{id}/": Endpoints.delete_Integrations_destroy;
        "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.delete_Session_recordings_destroy;
        "/api/projects/{project_id}/surveys/{id}/": Endpoints.delete_Surveys_destroy;
        "/api/projects/{project_id}/tasks/{id}/": Endpoints.delete_Tasks_destroy;
        "/api/users/{uuid}/": Endpoints.delete_Users_destroy;
    };
    post: {
        "/api/projects/{project_id}/comments/": Endpoints.post_Comments_create;
        "/api/projects/{project_id}/evaluations/": Endpoints.post_Evaluations_create;
        "/api/projects/{project_id}/external_data_sources/": Endpoints.post_External_data_sources_create;
        "/api/projects/{project_id}/feature_flags/": Endpoints.post_Feature_flags_create;
        "/api/projects/{project_id}/hog_flows/": Endpoints.post_Hog_flows_create;
        "/api/projects/{project_id}/hog_flows/{id}/run/": Endpoints.post_Hog_flows_run_create;
        "/api/projects/{project_id}/hog_flows/{id}/schedules/": Endpoints.post_Hog_flows_schedules_create;
        "/api/projects/{project_id}/tasks/": Endpoints.post_Tasks_create;
        "/api/projects/{project_id}/tasks/{id}/run/": Endpoints.post_Tasks_run_create;
        "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/analyze/": Endpoints.post_Tasks_runs_analyze_create;
    };
};

// </EndpointByMethod>

// <EndpointByMethod.Shorthands>
export type GetEndpoints = EndpointByMethod["get"];
export type PutEndpoints = EndpointByMethod["put"];
export type PatchEndpoints = EndpointByMethod["patch"];
export type DeleteEndpoints = EndpointByMethod["delete"];
export type PostEndpoints = EndpointByMethod["post"];
// </EndpointByMethod.Shorthands>

// <ApiClientTypes>
export type EndpointParameters = {
    body?: unknown;
    query?: Record<string, unknown>;
    header?: Record<string, unknown>;
    path?: Record<string, unknown>;
};

export type MutationMethod = "post" | "put" | "patch" | "delete";
export type Method = "get" | "head" | "options" | MutationMethod;

type RequestFormat = "json" | "form-data" | "form-url" | "binary" | "text";

export type DefaultEndpoint = {
    parameters?: EndpointParameters | undefined;
    responses?: Record<string, unknown>;
    responseHeaders?: Record<string, unknown>;
};

export type Endpoint<TConfig extends DefaultEndpoint = DefaultEndpoint> = {
    operationId: string;
    method: Method;
    path: string;
    requestFormat: RequestFormat;
    parameters?: TConfig["parameters"];
    meta: {
        alias: string;
        hasParameters: boolean;
        areParametersRequired: boolean;
    };
    responses?: TConfig["responses"];
    responseHeaders?: TConfig["responseHeaders"];
};

export interface Fetcher {
    decodePathParams?: (
        path: string,
        pathParams: Record<string, string>,
    ) => string;
    encodeSearchParams?: (
        searchParams: Record<string, unknown> | undefined,
    ) => URLSearchParams;
    //
    fetch: (input: {
        method: Method;
        url: URL;
        urlSearchParams?: URLSearchParams | undefined;
        parameters?: EndpointParameters | undefined;
        path: string;
        overrides?: RequestInit;
        throwOnStatusError?: boolean;
    }) => Promise<Response>;
    parseResponseData?: (response: Response) => Promise<unknown>;
}

export const successStatusCodes = [
    200, 201, 202, 203, 204, 205, 206, 207, 208, 226, 300, 301, 302, 303, 304,
    305, 306, 307, 308,
] as const;
export type SuccessStatusCode = (typeof successStatusCodes)[number];

export const errorStatusCodes = [
    400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414,
    415, 416, 417, 418, 421, 422, 423, 424, 425, 426, 428, 429, 431, 451, 500,
    501, 502, 503, 504, 505, 506, 507, 508, 510, 511,
] as const;
export type ErrorStatusCode = (typeof errorStatusCodes)[number];

// Taken from https://github.com/unjs/fetchdts/blob/ec4eaeab5d287116171fc1efd61f4a1ad34e4609/src/fetch.ts#L3
export interface TypedHeaders<
    TypedHeaderValues extends Record<string, string> | unknown,
> extends Omit<
    Headers,
    "append" | "delete" | "get" | "getSetCookie" | "has" | "set" | "forEach"
> {
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/append) */
    append: <
        Name extends Extract<keyof TypedHeaderValues, string> | (string & {}),
    >(
        name: Name,
        value: Lowercase<Name> extends keyof TypedHeaderValues
            ? TypedHeaderValues[Lowercase<Name>]
            : string,
    ) => void;
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/delete) */
    delete: <
        Name extends Extract<keyof TypedHeaderValues, string> | (string & {}),
    >(
        name: Name,
    ) => void;
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/get) */
    get: <
        Name extends Extract<keyof TypedHeaderValues, string> | (string & {}),
    >(
        name: Name,
    ) =>
        | (Lowercase<Name> extends keyof TypedHeaderValues
              ? TypedHeaderValues[Lowercase<Name>]
              : string)
        | null;
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/getSetCookie) */
    getSetCookie: () => string[];
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/has) */
    has: <
        Name extends Extract<keyof TypedHeaderValues, string> | (string & {}),
    >(
        name: Name,
    ) => boolean;
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/set) */
    set: <
        Name extends Extract<keyof TypedHeaderValues, string> | (string & {}),
    >(
        name: Name,
        value: Lowercase<Name> extends keyof TypedHeaderValues
            ? TypedHeaderValues[Lowercase<Name>]
            : string,
    ) => void;
    forEach: (
        callbackfn: (
            value: TypedHeaderValues[keyof TypedHeaderValues] | (string & {}),
            key: Extract<keyof TypedHeaderValues, string> | (string & {}),
            parent: TypedHeaders<TypedHeaderValues>,
        ) => void,
        thisArg?: any,
    ) => void;
}

/** @see https://developer.mozilla.org/en-US/docs/Web/API/Response */
export interface TypedSuccessResponse<
    TSuccess,
    TStatusCode,
    THeaders,
> extends Omit<Response, "ok" | "status" | "json" | "headers"> {
    ok: true;
    status: TStatusCode;
    headers: never extends THeaders ? Headers : TypedHeaders<THeaders>;
    data: TSuccess;
    /** [MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/Response/json) */
    json: () => Promise<TSuccess>;
}

/** @see https://developer.mozilla.org/en-US/docs/Web/API/Response */
export interface TypedErrorResponse<TData, TStatusCode, THeaders> extends Omit<
    Response,
    "ok" | "status" | "json" | "headers"
> {
    ok: false;
    status: TStatusCode;
    headers: never extends THeaders ? Headers : TypedHeaders<THeaders>;
    data: TData;
    /** [MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/Response/json) */
    json: () => Promise<TData>;
}

export type TypedApiResponse<
    TAllResponses extends Record<string | number, unknown> = {},
    THeaders = {},
> = {
    [K in keyof TAllResponses]: K extends string
        ? K extends `${infer TStatusCode extends number}`
            ? TStatusCode extends SuccessStatusCode
                ? TypedSuccessResponse<
                      TAllResponses[K],
                      TStatusCode,
                      K extends keyof THeaders ? THeaders[K] : never
                  >
                : TypedErrorResponse<
                      TAllResponses[K],
                      TStatusCode,
                      K extends keyof THeaders ? THeaders[K] : never
                  >
            : never
        : K extends number
          ? K extends SuccessStatusCode
              ? TypedSuccessResponse<
                    TAllResponses[K],
                    K,
                    K extends keyof THeaders ? THeaders[K] : never
                >
              : TypedErrorResponse<
                    TAllResponses[K],
                    K,
                    K extends keyof THeaders ? THeaders[K] : never
                >
          : never;
}[keyof TAllResponses];

export type SafeApiResponse<TEndpoint> = TEndpoint extends {
    responses: infer TResponses;
}
    ? TResponses extends Record<string, unknown>
        ? TypedApiResponse<
              TResponses,
              TEndpoint extends { responseHeaders: infer THeaders }
                  ? THeaders
                  : never
          >
        : never
    : never;

export type InferResponseByStatus<TEndpoint, TStatusCode> = Extract<
    SafeApiResponse<TEndpoint>,
    { status: TStatusCode }
>;

type RequiredKeys<T> = {
    [P in keyof T]-?: undefined extends T[P] ? never : P;
}[keyof T];

type MaybeOptionalArg<T> =
    RequiredKeys<T> extends never ? [config?: T] : [config: T];
type NotNever<T> = [T] extends [never] ? false : true;

// </ApiClientTypes>

// <TypedStatusError>
export class TypedStatusError<TData = unknown> extends Error {
    response: TypedErrorResponse<TData, ErrorStatusCode, unknown>;
    status: number;
    constructor(response: TypedErrorResponse<TData, ErrorStatusCode, unknown>) {
        super(`HTTP ${response.status}: ${response.statusText}`);
        this.name = "TypedStatusError";
        this.response = response;
        this.status = response.status;
    }
}
// </TypedStatusError>

// <ApiClient>
export class ApiClient {
    baseUrl: string = "";
    successStatusCodes = successStatusCodes;
    errorStatusCodes = errorStatusCodes;

    constructor(public fetcher: Fetcher) {}

    setBaseUrl(baseUrl: string) {
        this.baseUrl = baseUrl;
        return this;
    }

    /**
     * Replace path parameters in URL
     * Supports both OpenAPI format {param} and Express format :param
     */
    defaultDecodePathParams = (
        url: string,
        params: Record<string, string>,
    ): string => {
        return url
            .replace(/{(\w+)}/g, (_, key: string) => params[key] || `{${key}}`)
            .replace(
                /:([a-zA-Z0-9_]+)/g,
                (_, key: string) => params[key] || `:${key}`,
            );
    };

    /** Uses URLSearchParams, skips null/undefined values */
    defaultEncodeSearchParams = (
        queryParams: Record<string, unknown> | undefined,
    ): URLSearchParams | undefined => {
        if (!queryParams) return;

        const searchParams = new URLSearchParams();
        Object.entries(queryParams).forEach(([key, value]) => {
            if (value != null) {
                // Skip null/undefined values
                if (Array.isArray(value)) {
                    value.forEach(
                        (val) =>
                            val != null &&
                            searchParams.append(key, String(val)),
                    );
                } else {
                    searchParams.append(key, String(value));
                }
            }
        });

        return searchParams;
    };

    defaultParseResponseData = async (response: Response): Promise<unknown> => {
        const contentType = response.headers.get("content-type") ?? "";
        if (contentType.startsWith("text/")) {
            return await response.text();
        }

        if (contentType === "application/octet-stream") {
            return await response.arrayBuffer();
        }

        if (
            contentType.includes("application/json") ||
            (contentType.includes("application/") &&
                contentType.includes("json")) ||
            contentType === "*/*"
        ) {
            try {
                return await response.json();
            } catch {
                return undefined;
            }
        }

        return;
    };

    // <ApiClient.get>
    get<Path extends keyof GetEndpoints, TEndpoint extends GetEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: false;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<
        Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"]
    >;

    get<Path extends keyof GetEndpoints, TEndpoint extends GetEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: true;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<SafeApiResponse<TEndpoint>>;

    get<Path extends keyof GetEndpoints, _TEndpoint extends GetEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request("get", path, ...params);
    }
    // </ApiClient.get>

    // <ApiClient.put>
    put<Path extends keyof PutEndpoints, TEndpoint extends PutEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: false;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<
        Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"]
    >;

    put<Path extends keyof PutEndpoints, TEndpoint extends PutEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: true;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<SafeApiResponse<TEndpoint>>;

    put<Path extends keyof PutEndpoints, _TEndpoint extends PutEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request("put", path, ...params);
    }
    // </ApiClient.put>

    // <ApiClient.patch>
    patch<
        Path extends keyof PatchEndpoints,
        TEndpoint extends PatchEndpoints[Path],
    >(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: false;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<
        Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"]
    >;

    patch<
        Path extends keyof PatchEndpoints,
        TEndpoint extends PatchEndpoints[Path],
    >(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: true;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<SafeApiResponse<TEndpoint>>;

    patch<
        Path extends keyof PatchEndpoints,
        _TEndpoint extends PatchEndpoints[Path],
    >(path: Path, ...params: MaybeOptionalArg<any>): Promise<any> {
        return this.request("patch", path, ...params);
    }
    // </ApiClient.patch>

    // <ApiClient.delete>
    delete<
        Path extends keyof DeleteEndpoints,
        TEndpoint extends DeleteEndpoints[Path],
    >(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: false;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<
        Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"]
    >;

    delete<
        Path extends keyof DeleteEndpoints,
        TEndpoint extends DeleteEndpoints[Path],
    >(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: true;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<SafeApiResponse<TEndpoint>>;

    delete<
        Path extends keyof DeleteEndpoints,
        _TEndpoint extends DeleteEndpoints[Path],
    >(path: Path, ...params: MaybeOptionalArg<any>): Promise<any> {
        return this.request("delete", path, ...params);
    }
    // </ApiClient.delete>

    // <ApiClient.post>
    post<
        Path extends keyof PostEndpoints,
        TEndpoint extends PostEndpoints[Path],
    >(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: false;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<
        Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"]
    >;

    post<
        Path extends keyof PostEndpoints,
        TEndpoint extends PostEndpoints[Path],
    >(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: true;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<SafeApiResponse<TEndpoint>>;

    post<
        Path extends keyof PostEndpoints,
        _TEndpoint extends PostEndpoints[Path],
    >(path: Path, ...params: MaybeOptionalArg<any>): Promise<any> {
        return this.request("post", path, ...params);
    }
    // </ApiClient.post>

    // <ApiClient.request>
    /**
     * Generic request method with full type-safety for any endpoint
     */
    request<
        TMethod extends keyof EndpointByMethod,
        TPath extends keyof EndpointByMethod[TMethod],
        TEndpoint extends EndpointByMethod[TMethod][TPath],
    >(
        method: TMethod,
        path: TPath,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: false;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: false;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<
        Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"]
    >;

    request<
        TMethod extends keyof EndpointByMethod,
        TPath extends keyof EndpointByMethod[TMethod],
        TEndpoint extends EndpointByMethod[TMethod][TPath],
    >(
        method: TMethod,
        path: TPath,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                    : {
                          overrides?: RequestInit;
                          withResponse?: true;
                          throwOnStatusError?: boolean;
                      }
                : {
                      overrides?: RequestInit;
                      withResponse?: true;
                      throwOnStatusError?: boolean;
                  }
        >
    ): Promise<SafeApiResponse<TEndpoint>>;

    request<
        TMethod extends keyof EndpointByMethod,
        TPath extends keyof EndpointByMethod[TMethod],
        TEndpoint extends EndpointByMethod[TMethod][TPath],
    >(
        method: TMethod,
        path: TPath,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        const requestParams = params[0];
        const withResponse = requestParams?.withResponse;
        const {
            withResponse: _,
            throwOnStatusError = withResponse ? false : true,
            overrides,
            ...fetchParams
        } = requestParams || {};

        const parametersToSend: EndpointParameters = {};
        if (requestParams?.body !== undefined)
            (parametersToSend as any).body = requestParams.body;
        if (requestParams?.query !== undefined)
            (parametersToSend as any).query = requestParams.query;
        if (requestParams?.header !== undefined)
            (parametersToSend as any).header = requestParams.header;
        if (requestParams?.path !== undefined)
            (parametersToSend as any).path = requestParams.path;

        const resolvedPath = (
            this.fetcher.decodePathParams ?? this.defaultDecodePathParams
        )(
            this.baseUrl + (path as string),
            (parametersToSend.path ?? {}) as Record<string, string>,
        );
        const url = new URL(resolvedPath);
        const urlSearchParams = (
            this.fetcher.encodeSearchParams ?? this.defaultEncodeSearchParams
        )(parametersToSend.query);

        const promise = this.fetcher
            .fetch({
                method: method,
                path: path as string,
                url,
                urlSearchParams,
                parameters: Object.keys(fetchParams).length
                    ? fetchParams
                    : undefined,
                overrides,
                throwOnStatusError,
            })
            .then(async (response) => {
                const data = await (
                    this.fetcher.parseResponseData ??
                    this.defaultParseResponseData
                )(response);
                const typedResponse = Object.assign(response, {
                    data: data,
                    json: () => Promise.resolve(data),
                }) as SafeApiResponse<TEndpoint>;

                if (
                    throwOnStatusError &&
                    errorStatusCodes.includes(response.status as never)
                ) {
                    throw new TypedStatusError(typedResponse as never);
                }

                return withResponse ? typedResponse : data;
            });

        return promise as Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >["data"];
    }
    // </ApiClient.request>
}

export function createApiClient(fetcher: Fetcher, baseUrl?: string) {
    return new ApiClient(fetcher).setBaseUrl(baseUrl ?? "");
}

/**
 Example usage:
 const api = createApiClient((method, url, params) =>
   fetch(url, { method, body: JSON.stringify(params) }).then((res) => res.json()),
 );
 api.get("/users").then((users) => console.log(users));
 api.post("/users", { body: { name: "John" } }).then((user) => console.log(user));
 api.put("/users/:id", { path: { id: 1 }, body: { name: "John" } }).then((user) => console.log(user));

 // With error handling
 const result = await api.get("/users/{id}", { path: { id: "123" }, withResponse: true });
 if (result.ok) {
   // Access data directly
   const user = result.data;
   console.log(user);

   // Or use the json() method for compatibility
   const userFromJson = await result.json();
   console.log(userFromJson);
 } else {
   const error = result.data;
   console.error(`Error ${result.status}:`, error);
 }
*/

// </ApiClient>
