import * as antd_lib_checkbox_Group from 'antd/lib/checkbox/Group';
import React, { MouseEventHandler, HTMLProps, ReactNode } from 'react';
import { UploadFile } from 'antd/lib/upload/interface';
import { Placement } from '@popperjs/core';
import { ModalProps } from 'antd';
import { ToastOptions } from 'react-toastify';

/** Collaboration restriction level (which is a dashboard setting). Sync with DashboardPrivilegeLevel. */
declare enum DashboardRestrictionLevel$1 {
    EveryoneInProjectCanEdit = 21,
    OnlyCollaboratorsCanEdit = 37
}
/** Collaboration privilege level (which is a user property). Sync with DashboardRestrictionLevel. */
declare enum DashboardPrivilegeLevel$1 {
    CanView = 21,
    CanEdit = 37,
    /** This is not a value that can be set in the DB – it's inferred. */
    _ProjectAdmin = 888,
    /** This is not a value that can be set in the DB – it's inferred. */
    _Owner = 999
}
declare enum ShownAsValue$1 {
    VOLUME = "Volume",
    STICKINESS = "Stickiness",
    LIFECYCLE = "Lifecycle"
}
declare const RETENTION_RECURRING$1 = "retention_recurring";
declare const RETENTION_FIRST_TIME$1 = "retention_first_time";
declare const ENTITY_MATCH_TYPE$1 = "entities";
declare const PROPERTY_MATCH_TYPE$1 = "properties";
declare enum FunnelLayout$1 {
    horizontal = "horizontal",
    vertical = "vertical"
}
declare const BIN_COUNT_AUTO$1 = "auto";

declare enum TaxonomicFilterGroupType$1 {
    Actions = "actions",
    Cohorts = "cohorts",
    CohortsWithAllUsers = "cohorts_with_all",
    Elements = "elements",
    Events = "events",
    EventProperties = "event_properties",
    NumericalEventProperties = "numerical_event_properties",
    PersonProperties = "person_properties",
    PageviewUrls = "pageview_urls",
    Screens = "screens",
    CustomEvents = "custom_events",
    Wildcards = "wildcard",
    GroupsPrefix = "groups",
    Persons = "persons",
    FeatureFlags = "feature_flags",
    Insights = "insights",
    Experiments = "experiments",
    Plugins = "plugins",
    Dashboards = "dashboards",
    GroupNamesPrefix = "name_groups"
}

declare module 'react' {
    function forwardRef<T, P>(render: (props: P, ref: React.Ref<T>) => React.ReactElement | null): (props: P & React.RefAttributes<T>) => React.ReactElement | null;
}

declare type BehavioralFilterType$1 = BehavioralEventType$1 | BehavioralCohortType$1 | BehavioralLifecycleType$1;
declare enum BehavioralFilterKey$1 {
    Behavioral = "behavioral",
    Cohort = "cohort",
    Person = "person"
}

declare enum LicensePlan$1 {
    Scale = "scale",
    Enterprise = "enterprise"
}
interface UserBaseType$1 {
    uuid: string;
    distinct_id: string;
    first_name: string;
    email: string;
}
interface UserBasicType$1 extends UserBaseType$1 {
    id: number;
}
interface ActionType$1 {
    count?: number;
    created_at: string;
    deleted?: boolean;
    id: number;
    is_calculating?: boolean;
    last_calculated_at?: string;
    name: string | null;
    description?: string;
    post_to_slack?: boolean;
    slack_message_format?: string;
    steps?: ActionStepType$1[];
    created_by: UserBasicType$1 | null;
    tags?: string[];
}
/** Sync with plugin-server/src/types.ts */
declare enum ActionStepUrlMatching$1 {
    Contains = "contains",
    Regex = "regex",
    Exact = "exact"
}
interface ActionStepType$1 {
    event?: string;
    href?: string | null;
    id?: number;
    name?: string;
    properties?: AnyPropertyFilter$1[];
    selector?: string | null;
    tag_name?: string;
    text?: string | null;
    url?: string | null;
    url_matching?: ActionStepUrlMatching$1;
    isNew?: string;
}
interface ElementType$1 {
    attr_class?: string[];
    attr_id?: string;
    attributes: Record<string, string>;
    href: string;
    nth_child: number;
    nth_of_type: number;
    order: number;
    tag_name: string;
    text?: string;
}
declare type PropertyFilterValue$1 = string | number | (string | number)[] | null;
interface PropertyFilter$1 {
    key: string;
    operator: PropertyOperator$1 | null;
    type: string;
    value: PropertyFilterValue$1;
    group_type_index?: number | null;
}
declare type EmptyPropertyFilter$1 = Partial<PropertyFilter$1>;
declare type AnyPropertyFilter$1 = PropertyFilter$1 | EmptyPropertyFilter$1;
/** Sync with plugin-server/src/types.ts */
declare enum PropertyOperator$1 {
    Exact = "exact",
    IsNot = "is_not",
    IContains = "icontains",
    NotIContains = "not_icontains",
    Regex = "regex",
    NotRegex = "not_regex",
    GreaterThan = "gt",
    GreaterThanOrEqual = "gte",
    LessThan = "lt",
    LessThanOrEqual = "lte",
    IsSet = "is_set",
    IsNotSet = "is_not_set",
    IsDateExact = "is_date_exact",
    IsDateBefore = "is_date_before",
    IsDateAfter = "is_date_after",
    Between = "between",
    NotBetween = "not_between",
    Minimum = "min",
    Maximum = "max"
}
declare type EntityType$1 = 'actions' | 'events' | 'new_entity';
interface Entity$1 {
    id: string | number;
    name: string;
    custom_name?: string;
    order: number;
    type: EntityType$1;
}
declare type EntityFilter$1 = {
    type?: EntityType$1;
    id: Entity$1['id'] | null;
    name: string | null;
    custom_name?: string;
    index?: number;
    order?: number;
};
interface FunnelStepRangeEntityFilter$1 {
    funnel_from_step?: number;
    funnel_to_step?: number;
}
interface PersonType$1 {
    id?: number;
    uuid?: string;
    name?: string;
    distinct_ids: string[];
    properties: Record<string, any>;
    created_at?: string;
    is_identified?: boolean;
}
interface MatchedRecordingEvents$1 {
    uuid: string;
    window_id: string;
    timestamp: string;
}
interface MatchedRecording$1 {
    session_id: string;
    events: MatchedRecordingEvents$1[];
}
interface CommonActorType$1 {
    id?: string | number;
    properties: Record<string, any>;
    created_at?: string;
    matched_recordings?: MatchedRecording$1[];
}
interface PersonActorType$1 extends CommonActorType$1 {
    type: 'person';
    uuid?: string;
    name?: string;
    distinct_ids: string[];
    is_identified: boolean;
}
interface GroupActorType$1 extends CommonActorType$1 {
    type: 'group';
    group_key: string;
    group_type_index: number;
}
declare type ActorType$1 = PersonActorType$1 | GroupActorType$1;
interface CohortGroupType$1 {
    id: string;
    days?: string;
    action_id?: number;
    event_id?: string;
    label?: string;
    count?: number;
    count_operator?: string;
    properties?: AnyPropertyFilter$1[];
    matchType: MatchType$1;
    name?: string;
}
interface CohortCriteriaType$1 {
    id: string;
    key: string;
    value: BehavioralFilterType$1;
    type: BehavioralFilterKey$1;
    operator?: PropertyOperator$1 | null;
    group_type_index?: number | null;
    event_type?: TaxonomicFilterGroupType$1 | null;
    operator_value?: PropertyFilterValue$1;
    time_value?: number | string | null;
    time_interval?: TimeUnitType$1 | null;
    total_periods?: number | null;
    min_periods?: number | null;
    seq_event_type?: TaxonomicFilterGroupType$1 | null;
    seq_event?: string | number | null;
    seq_time_value?: number | string | null;
    seq_time_interval?: TimeUnitType$1 | null;
    negation?: boolean;
    value_property?: string | null;
}
declare type EmptyCohortCriteriaType$1 = Partial<CohortCriteriaType$1>;
declare type AnyCohortCriteriaType$1 = CohortCriteriaType$1 | EmptyCohortCriteriaType$1;
declare type MatchType$1 = typeof ENTITY_MATCH_TYPE$1 | typeof PROPERTY_MATCH_TYPE$1;
interface CohortType$1 {
    count?: number;
    description?: string;
    created_by?: UserBasicType$1 | null;
    created_at?: string;
    deleted?: boolean;
    id: number | 'new';
    is_calculating?: boolean;
    errors_calculating?: number;
    last_calculation?: string;
    is_static?: boolean;
    name?: string;
    csv?: UploadFile;
    groups: CohortGroupType$1[];
    filters: {
        properties: CohortCriteriaGroupFilter$1;
    };
}
declare type BinCountValue$1 = number | typeof BIN_COUNT_AUTO$1;
declare enum StepOrderValue$1 {
    STRICT = "strict",
    UNORDERED = "unordered",
    ORDERED = "ordered"
}
interface EventType$1 {
    elements: ElementType$1[];
    elements_hash: string | null;
    elements_chain?: string | null;
    id: number | string;
    properties: Record<string, any>;
    timestamp: string;
    colonTimestamp?: string;
    person?: Partial<PersonType$1> | null;
    event: string;
}
declare type InsightShortId$1 = string & {
    readonly '': unique symbol;
};
declare enum InsightColor$1 {
    White = "white",
    Black = "black",
    Blue = "blue",
    Green = "green",
    Purple = "purple"
}
interface DashboardTile$1 {
    result: any | null;
    layouts: Record<string, any>;
    color: InsightColor$1 | null;
    last_refresh: string | null;
    filters: Partial<FilterType$1>;
    filters_hash: string;
}
interface InsightModel$1 extends DashboardTile$1 {
    /** The unique key we use when communicating with the user, e.g. in URLs */
    short_id: InsightShortId$1;
    /** The primary key in the database, used as well in API endpoints */
    id: number;
    name: string;
    derived_name?: string;
    description?: string;
    favorited?: boolean;
    order: number | null;
    deleted: boolean;
    saved: boolean;
    created_at: string;
    created_by: UserBasicType$1 | null;
    refreshing: boolean;
    is_sample: boolean;
    dashboards: number[] | null;
    updated_at: string;
    tags?: string[];
    last_modified_at: string;
    last_modified_by: UserBasicType$1 | null;
    effective_restriction_level: DashboardRestrictionLevel$1;
    effective_privilege_level: DashboardPrivilegeLevel$1;
    timezone?: string;
    /** Only used in the frontend to store the next breakdown url */
    next?: string;
}
interface DashboardType$1 {
    id: number;
    name: string;
    description: string;
    pinned: boolean;
    items: InsightModel$1[];
    created_at: string;
    created_by: UserBasicType$1 | null;
    is_shared: boolean;
    share_token: string;
    deleted: boolean;
    filters: Record<string, any>;
    creation_mode: 'default' | 'template' | 'duplicate';
    restriction_level: DashboardRestrictionLevel$1;
    effective_restriction_level: DashboardRestrictionLevel$1;
    effective_privilege_level: DashboardPrivilegeLevel$1;
    tags?: string[];
    /** Purely local value to determine whether the dashboard should be highlighted, e.g. as a fresh duplicate. */
    _highlight?: boolean;
}
/** Explicit dashboard collaborator, based on DashboardPrivilege. */
interface DashboardCollaboratorType$1 {
    id: string;
    dashboard_id: DashboardType$1['id'];
    user: UserBasicType$1;
    level: DashboardPrivilegeLevel$1;
    added_at: string;
    updated_at: string;
}
declare enum PluginLogEntryType$1 {
    Debug = "DEBUG",
    Log = "LOG",
    Info = "INFO",
    Warn = "WARN",
    Error = "ERROR"
}
interface PluginLogEntry$1 {
    id: string;
    team_id: number;
    plugin_id: number;
    plugin_config_id: number;
    timestamp: string;
    type: PluginLogEntryType$1;
    is_system: boolean;
    message: string;
    instance_id: string;
}
declare enum ChartDisplayType$1 {
    ActionsLineGraph = "ActionsLineGraph",
    ActionsLineGraphCumulative = "ActionsLineGraphCumulative",
    ActionsTable = "ActionsTable",
    ActionsPie = "ActionsPie",
    ActionsBar = "ActionsBar",
    ActionsBarValue = "ActionsBarValue",
    PathsViz = "PathsViz",
    FunnelViz = "FunnelViz",
    WorldMap = "WorldMap"
}
declare type BreakdownType$1 = 'cohort' | 'person' | 'event' | 'group';
declare type IntervalType$1 = 'hour' | 'day' | 'week' | 'month';
declare enum InsightType$1 {
    TRENDS = "TRENDS",
    STICKINESS = "STICKINESS",
    LIFECYCLE = "LIFECYCLE",
    FUNNELS = "FUNNELS",
    RETENTION = "RETENTION",
    PATHS = "PATHS"
}
declare enum PathType$1 {
    PageView = "$pageview",
    Screen = "$screen",
    CustomEvent = "custom_event"
}
declare enum FunnelPathType$1 {
    before = "funnel_path_before_step",
    between = "funnel_path_between_steps",
    after = "funnel_path_after_step"
}
declare enum FunnelVizType$1 {
    Steps = "steps",
    TimeToConvert = "time_to_convert",
    Trends = "trends"
}
declare type RetentionType$1 = typeof RETENTION_RECURRING$1 | typeof RETENTION_FIRST_TIME$1;
declare type BreakdownKeyType$1 = string | number | (string | number)[] | null;
interface Breakdown$1 {
    property: string | number;
    type: BreakdownType$1;
}
interface FilterType$1 {
    insight?: InsightType$1;
    display?: ChartDisplayType$1;
    interval?: IntervalType$1;
    smoothing_intervals?: number;
    date_from?: string | null;
    date_to?: string | null;
    properties?: AnyPropertyFilter$1[] | PropertyGroupFilter$1;
    events?: Record<string, any>[];
    event?: string;
    actions?: Record<string, any>[];
    breakdown_type?: BreakdownType$1 | null;
    breakdown?: BreakdownKeyType$1;
    breakdowns?: Breakdown$1[];
    breakdown_value?: string | number;
    breakdown_group_type_index?: number | null;
    shown_as?: ShownAsValue$1;
    session?: string;
    period?: string;
    retention_type?: RetentionType$1;
    retention_reference?: 'total' | 'previous';
    total_intervals?: number;
    new_entity?: Record<string, any>[];
    returning_entity?: Record<string, any>;
    target_entity?: Record<string, any>;
    path_type?: PathType$1;
    include_event_types?: PathType$1[];
    start_point?: string;
    end_point?: string;
    path_groupings?: string[];
    stickiness_days?: number;
    type?: EntityType$1;
    entity_id?: string | number;
    entity_type?: EntityType$1;
    entity_math?: string;
    people_day?: any;
    people_action?: any;
    formula?: any;
    filter_test_accounts?: boolean;
    from_dashboard?: boolean | number;
    layout?: FunnelLayout$1;
    funnel_step?: number;
    entrance_period_start?: string;
    drop_off?: boolean;
    funnel_viz_type?: FunnelVizType$1;
    funnel_from_step?: number;
    funnel_to_step?: number;
    funnel_step_breakdown?: string | number[] | number | null;
    compare?: boolean;
    bin_count?: BinCountValue$1;
    funnel_window_interval_unit?: FunnelConversionWindowTimeUnit$1;
    funnel_window_interval?: number | undefined;
    funnel_order_type?: StepOrderValue$1;
    exclusions?: FunnelStepRangeEntityFilter$1[];
    exclude_events?: string[];
    step_limit?: number;
    path_start_key?: string;
    path_end_key?: string;
    path_dropoff_key?: string;
    path_replacements?: boolean;
    local_path_cleaning_filters?: Record<string, any>[];
    funnel_filter?: Record<string, any>;
    funnel_paths?: FunnelPathType$1;
    edge_limit?: number | undefined;
    min_edge_weight?: number | undefined;
    max_edge_weight?: number | undefined;
    funnel_correlation_person_entity?: Record<string, any>;
    funnel_correlation_person_converted?: 'true' | 'false';
    funnel_custom_steps?: number[];
    aggregation_group_type_index?: number | undefined;
    funnel_advanced?: boolean;
    show_legend?: boolean;
    hidden_legend_keys?: Record<string, boolean | undefined>;
}
interface ActionFilter$1 extends EntityFilter$1 {
    math?: string;
    math_property?: string;
    math_group_type_index?: number | null;
    properties?: PropertyFilter$1[];
    type: EntityType$1;
}
declare enum FunnelConversionWindowTimeUnit$1 {
    Minute = "minute",
    Hour = "hour",
    Day = "day",
    Week = "week",
    Month = "month"
}
interface LicenseType$1 {
    id: number;
    key: string;
    plan: LicensePlan$1;
    valid_until: string;
    max_users: number | null;
    created_at: string;
}
interface EventDefinition$1 {
    id: string;
    name: string;
    description: string;
    tags?: string[];
    volume_30_day: number | null;
    query_usage_30_day: number | null;
    owner?: UserBasicType$1 | null;
    created_at?: string;
    last_seen_at?: string;
    updated_at?: string;
    updated_by?: UserBasicType$1 | null;
    verified?: boolean;
    verified_at?: string;
    verified_by?: string;
}
declare enum PropertyType$1 {
    DateTime = "DateTime",
    String = "String",
    Numeric = "Numeric",
    Boolean = "Boolean"
}
interface PropertyDefinition$1 {
    id: string;
    name: string;
    description: string;
    tags?: string[];
    volume_30_day: number | null;
    query_usage_30_day: number | null;
    updated_at?: string;
    updated_by?: UserBasicType$1 | null;
    is_numerical?: boolean;
    is_event_property?: boolean;
    property_type?: PropertyType$1;
    created_at?: string;
    last_seen_at?: string;
    example?: string;
}
declare enum FilterLogicalOperator$1 {
    And = "AND",
    Or = "OR"
}
interface PropertyGroupFilter$1 {
    type: FilterLogicalOperator$1;
    values: PropertyGroupFilterValue$1[];
}
interface PropertyGroupFilterValue$1 {
    type: FilterLogicalOperator$1;
    values: AnyPropertyFilter$1[];
}
interface CohortCriteriaGroupFilter$1 {
    id?: string;
    type: FilterLogicalOperator$1;
    values: AnyCohortCriteriaType$1[] | CohortCriteriaGroupFilter$1[];
}
declare enum BehavioralEventType$1 {
    PerformEvent = "performed_event",
    PerformMultipleEvents = "performed_event_multiple",
    PerformSequenceEvents = "performed_event_sequence",
    NotPerformedEvent = "not_performed_event",
    NotPerformSequenceEvents = "not_performed_event_sequence",
    HaveProperty = "have_property",
    NotHaveProperty = "not_have_property"
}
declare enum BehavioralCohortType$1 {
    InCohort = "in_cohort",
    NotInCohort = "not_in_cohort"
}
declare enum BehavioralLifecycleType$1 {
    PerformEventFirstTime = "performed_event_first_time",
    PerformEventRegularly = "performed_event_regularly",
    StopPerformEvent = "stopped_performing_event",
    StartPerformEventAgain = "restarted_performing_event"
}
declare enum TimeUnitType$1 {
    Day = "day",
    Week = "week",
    Month = "month",
    Year = "year"
}

interface PersonFilters$1 {
    properties?: AnyPropertyFilter$1[];
    search?: string;
    cohort?: number;
}

interface ActivityChange$1 {
    type: 'FeatureFlag' | 'Person' | 'Insight';
    action: 'changed' | 'created' | 'deleted';
    field?: string;
    before?: string | Record<string, any> | boolean;
    after?: string | Record<string, any> | boolean;
}
interface PersonMerge$1 {
    type: 'Person';
    source: PersonType$1[];
    target: PersonType$1;
}
interface ActivityLogDetail$1 {
    merge: PersonMerge$1 | null;
    changes: ActivityChange$1[] | null;
    name: string | null;
    short_id?: InsightShortId$1 | null;
}
interface ActivityUser$1 {
    email: string;
    first_name: string;
}
declare enum ActivityScope$1 {
    FEATURE_FLAG = "FeatureFlag",
    PERSON = "Person",
    INSIGHT = "Insight"
}
interface ActivityLogItem$1 {
    user: ActivityUser$1;
    activity: string;
    created_at: string;
    scope: ActivityScope$1;
    item_id?: string;
    detail: ActivityLogDetail$1;
}
declare type Describer$1 = (logItem: ActivityLogItem$1) => string | JSX.Element | null;

interface ActivityLogProps$1 {
    scope: ActivityScope$1;
    id?: number;
    describer?: Describer$1;
    startingPage?: number;
    caption?: string | JSX.Element;
}

interface PeopleParamType$1 {
    action?: ActionFilter$1;
    label: string;
    date_to?: string | number;
    date_from?: string | number;
    breakdown_value?: string | number;
    target_date?: number | string;
    lifecycle_type?: string | number;
}

interface PaginatedResponse$1<T> {
    results: T[];
    next?: string;
    previous?: string;
}
interface CountedPaginatedResponse$1 extends PaginatedResponse$1<ActivityLogItem$1> {
    total_count: number;
}

interface LemonBubbleProps {
	count?: number;
	size?: "small" | "medium" | "large";
	position?: "none" | "top-left" | "top-right" | "bottom-left" | "bottom-right";
	showZero?: boolean;
}
/** An icon-sized Bubble for displaying a count.
 *
 *  Numbers up to 9 are displayed in full, in integer form, with 9+ for higher values
 */
declare function LemonBubble({ count, size, position, showZero, }: LemonBubbleProps): JSX.Element;
interface LemonRowPropsBase<T extends keyof JSX.IntrinsicElements> extends Omit<React.HTMLProps<JSX.IntrinsicElements[T]>, "ref" | "size"> {
	/** If icon width is relaxed, width of icon box is set to auto. Default icon width is 1em  */
	relaxedIconWidth?: boolean;
	icon?: React.ReactElement | null;
	/** HTML tag to render the row with. */
	tag?: T;
	status?: "success" | "warning" | "danger" | "highlighted" | "muted";
	/** Extended content, e.g. a description, to show in the lower button area. */
	extendedContent?: React.ReactNode;
	loading?: boolean;
	/** Tooltip to display on hover. */
	tooltip?: any;
	/** Whether the row should take up the parent's full width. */
	fullWidth?: boolean;
	/** Whether the row's contents should be centered. */
	center?: boolean;
	/** Whether the element should be outlined with a standard border. */
	outlined?: any;
	/** Variation on sizes - default is medium. Small looks better inline with text. Large is a chunkier row.  */
	size?: "small" | "medium" | "large";
	"data-attr"?: string;
}
interface LemonRowProps<T extends keyof JSX.IntrinsicElements = "div"> extends LemonRowPropsBase<T> {
	sideIcon?: React.ReactElement | false | null;
}
/** Generic UI row component. Can be exploited as a button (see LemonButton) or just as a standard row of content.
 *
 * Do NOT use for general layout if you simply need flexbox though. In that case `display: flex` is much lighter.
 */
declare const LemonRow: <T extends keyof JSX.IntrinsicElements = "div">(props: LemonRowProps<T> & React.RefAttributes<HTMLElement>) => React.ReactElement<any, string | React.JSXElementConstructor<any>> | null;
interface PopupProps {
	visible?: boolean;
	onClickOutside?: (event: Event) => void;
	onClickInside?: MouseEventHandler<HTMLDivElement>;
	/** Popover trigger element. */
	children: React.ReactChild | ((props: {
		setRef: (ref: HTMLElement | null) => void;
	}) => JSX.Element);
	/** Content of the overlay. */
	overlay: React.ReactNode | React.ReactNode[];
	/** Where the popover should start relative to children. */
	placement?: Placement;
	/** Where the popover should start relative to children if there's insufficient space for original placement. */
	fallbackPlacements?: Placement[];
	/** Whether the popover is actionable rather than just informative - actionable means a colored border. */
	actionable?: boolean;
	/** Whether the popover's width should be synced with the children's width. */
	sameWidth?: boolean;
	className?: string;
	modifier?: Record<string, any>;
}
interface LemonButtonPopup extends Omit<PopupProps, "children"> {
	closeOnClickInside?: boolean;
}
interface LemonButtonPropsBase extends Omit<LemonRowPropsBase<"button">, "tag" | "type" | "ref"> {
	ref?: React.Ref<HTMLButtonElement>;
	type?: "default" | "alt" | "primary" | "secondary" | "tertiary" | "stealth" | "highlighted";
	htmlType?: LemonRowPropsBase<"button">["type"];
	/** Whether the button should have transparent background in its base state (i.e. non-hover). */
	translucent?: boolean;
	/** Whether hover style should be applied, signaling that the button is held active in some way. */
	active?: boolean;
	/** URL to link to. */
	to?: string;
}
interface LemonButtonProps extends LemonButtonPropsBase {
	sideIcon?: React.ReactElement | null;
	/** DEPRECATED: Use `LemonButtonWithPopup` instead. */
	popup?: LemonButtonPopup;
}
declare const LemonButton: (props: LemonButtonProps & React.RefAttributes<HTMLButtonElement>) => React.ReactElement<any, string | React.JSXElementConstructor<any>> | null;
declare type SideAction = Pick<LemonButtonProps, "onClick" | "popup" | "to" | "disabled" | "icon" | "type" | "tooltip" | "data-attr">;
/** A LemonButtonWithSideAction can't have a sideIcon - instead it has a clickable sideAction. */
interface LemonButtonWithSideActionProps extends LemonButtonPropsBase {
	sideAction: SideAction;
}
/**
 * Styled button with a side action on the right.
 * We can't use `LemonRow`'s `sideIcon` prop because putting `onClick` on it clashes with the parent`s `onClick`.
 */
declare function LemonButtonWithSideAction({ sideAction, children, ...buttonProps }: LemonButtonWithSideActionProps): JSX.Element;
interface LemonButtonWithPopupProps extends LemonButtonPropsBase {
	popup: LemonButtonPopup;
	sideIcon?: React.ReactElement | null;
}
/**
 * Styled button that opens a popup menu on click.
 * The difference vs. plain `LemonButton` is popup visibility being controlled internally, which is more convenient.
 */
declare function LemonButtonWithPopup({ popup: { onClickOutside, onClickInside, closeOnClickInside, ...popupProps }, onClick, ...buttonProps }: LemonButtonWithPopupProps): JSX.Element;
interface LemonCheckboxProps {
	checked?: boolean | "indeterminate";
	defaultChecked?: boolean;
	disabled?: boolean;
	onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void;
	label?: string | JSX.Element;
	id?: string;
	className?: string;
	style?: React.CSSProperties;
	/** @deprecated See https://github.com/PostHog/posthog/pull/9357#pullrequestreview-933783868. */
	color?: string;
	rowProps?: LemonRowProps<"div">;
}
interface BoxCSSProperties extends React.CSSProperties {
	"--box-color": string;
}
/** `LemonRow`-based checkbox component for use in lists or forms.
 *
 * As opposed to switches, checkboxes don't always have to result in the change being applied immediately.
 * E.g. the change may only be applied when the user clicks "Save" in a form.
 */
declare function LemonCheckbox({ checked, defaultChecked, disabled, onChange, label, id: rawId, className, color, rowProps, style, }: LemonCheckboxProps): JSX.Element;
interface LemonDividerProps {
	/** Twice the default amount of margin. */
	large?: boolean;
	/** 3x the thickness of the line. */
	thick?: boolean;
	/** Whether the divider should be vertical (for separating left-to-right) instead of horizontal (top-to-bottom). */
	vertical?: boolean;
	/** Whether the divider should be a dashed line. */
	dashed?: boolean;
	style?: React.CSSProperties;
}
/** A separator, ideal for being sandwiched between `LemonRow`s.
 *
 * Horizontal by default but can be used in vertical form too.
 */
declare function LemonDivider({ large, vertical, dashed, thick, style, }: LemonDividerProps): JSX.Element;
interface LemonInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "defaultValue" | "onChange" | "prefix" | "suffix"> {
	ref?: React.Ref<HTMLInputElement>;
	id?: string;
	value?: string | number;
	defaultValue?: string;
	placeholder?: string;
	onChange?: (newValue: string) => void;
	onPressEnter?: (newValue: string) => void;
	/** An embedded input has no border around it and no background. This way it blends better into other components. */
	embedded?: boolean;
	/** Whether there should be a clear icon to the right allowing you to reset the input. The `suffix` prop will be ignored if clearing is allowed. */
	allowClear?: boolean;
	/** Icon to prefix input field */
	icon?: React.ReactElement | null;
	/** Icon to suffix input field */
	sideIcon?: React.ReactElement | null;
	/** Whether input field is disabled */
	disabled?: boolean;
}
/** A `LemonRow`-based `input` component for single-line text. */
declare const LemonInput: (props: LemonInputProps & React.RefAttributes<HTMLInputElement>) => React.ReactElement<any, string | React.JSXElementConstructor<any>> | null;
declare type LemonModalProps = React.PropsWithChildren<Omit<ModalProps, "closeIcon">>;
/** A lightweight wrapper over Ant's Modal for matching Lemon style. */
declare function LemonModal({ className, footer, width, ...modalProps }: LemonModalProps): JSX.Element;
interface LemonSelectOption {
	label: string;
	icon?: React.ReactElement;
	disabled?: boolean;
	"data-attr"?: string;
}
declare type LemonSelectOptions = Record<string | number, LemonSelectOption>;
interface LemonSelectProps<O extends LemonSelectOptions> extends Omit<LemonButtonWithPopupProps, "popup" | "icon" | "value" | "defaultValue" | "onChange"> {
	options: O;
	value?: keyof O | null;
	onChange?: (newValue: keyof O | null) => void;
	dropdownMatchSelectWidth?: boolean;
	allowClear?: boolean;
}
declare function LemonSelect<O extends LemonSelectOptions>({ value, onChange, options, placeholder, dropdownMatchSelectWidth, allowClear, ...buttonProps }: LemonSelectProps<O>): JSX.Element;
interface LemonSwitchProps extends Omit<LemonRowProps<"div">, "alt" | "label" | "onChange" | "outlined"> {
	onChange: (newChecked: boolean) => void;
	checked: boolean;
	label?: string | JSX.Element;
	/** Whether the switch should use the alternative primary color. */
	alt?: boolean;
	/** Default switches are inline. Primary switches _with a label_ are wrapped in an outlined block. */
	type?: "default" | "primary";
}
/** `LemonRow`-based switch component for boolean settings where the change is immediately applied.
 *
 * If part of a form, use `LemonCheckbox` instead.
 */
declare function LemonSwitch({ id: rawId, onChange, checked, disabled, loading, label, alt, type, className, "data-attr": dataAttr, ...rowProps }: LemonSwitchProps): JSX.Element;
/** Sorting state. */
interface Sorting {
	columnKey: string;
	/** 1 means ascending, -1 means descending. */
	order: 1 | -1;
}
interface TableCellRepresentation {
	children?: any;
	props?: HTMLProps<HTMLTableCellElement>;
}
declare type TableCellRenderResult = TableCellRepresentation | ReactNode | JSX.Element | string | number | false | null | undefined;
interface LemonTableColumn<T extends Record<string, any>, D extends keyof T | undefined> {
	title?: string | React.ReactNode;
	key?: string;
	dataIndex?: D;
	render?: (dataValue: D extends keyof T ? T[D] : undefined, record: T, recordIndex: number) => TableCellRenderResult;
	/** Sorting function. Set to `true` if using manual pagination, in which case you'll also have to provide `sorting` on the table. */
	sorter?: ((a: T, b: T) => number) | true;
	className?: string;
	/** Column content alignment. Left by default. Set to right for numerical values (amounts, days ago etc.) */
	align?: "left" | "right" | "center";
	/** TODO: Whether the column should be sticky when scrolling */
	sticky?: boolean;
	/** Set width. */
	width?: string | number;
}
interface LemonTableColumnGroup<T extends Record<string, any>> {
	title?: string | React.ReactNode;
	children: LemonTableColumn<T, keyof T | undefined>[];
}
declare type LemonTableColumns<T extends Record<string, any>> = LemonTableColumn<T, keyof T | undefined>[] | LemonTableColumnGroup<T>[];
interface ExpandableConfig<T extends Record<string, any>> {
	/** Row expansion render function. */
	expandedRowRender: (record: T, recordIndex: number) => any;
	/**
	 * Function determining whether the row should be expandable:
	 * A positive value (like true or 1) means that the row is expandable.
	 * A zero (like 0 or false) means that the row isn't expandable.
	 * A negative value (like -1) means that the row isn't expandable and that also the expand button cell is skipped.
	 */
	rowExpandable?: (record: T) => boolean | number;
	/** Called when row is expanded */
	onRowExpand?: (record: T) => void;
	/** Called when row is collapsed */
	onRowCollapse?: (record: T) => void;
	/** Disable indentation */
	noIndent?: boolean;
	/**
	 * Callback that checks if a row expandable state should be overridden
	 * A positive value (like true or 1) means that the row is expanded.
	 * A zero (like 0 or false) means that the row is collapsed.
	 * A negative value (like -1) means that the row is uncontrolled.
	 */
	isRowExpanded?: (record: T) => boolean | number;
}
interface PaginationBase {
	/** By default pagination is only shown when there are multiple pages, but will always be if this is `false`. */
	hideOnSinglePage?: boolean;
}
interface PaginationAuto extends PaginationBase {
	controlled?: false;
	/** Size of each page (except the last one which can be smaller). */
	pageSize: number;
}
interface PaginationManual extends PaginationBase {
	controlled: true;
	/** Size of each page (except the last one which can be smaller)/ */
	pageSize?: number;
	/** Page currently on display. */
	currentPage?: number;
	/** Total entry count for determining current position using `currentPage`. If not set, position is not shown. */
	entryCount?: number;
	/** Next page navigation handler. */
	onForward?: () => void;
	/** Previous page navigation handler. */
	onBackward?: () => void;
}
interface LemonTableProps<T extends Record<string, any>> {
	/** Table ID that will also be used in pagination to add uniqueness to search params (page + order). */
	id?: string;
	columns: LemonTableColumns<T>;
	dataSource: T[];
	/** Which column to use for the row key, as an alternative to the default row index mechanism. */
	rowKey?: keyof T | ((record: T) => string | number);
	/** Class to append to each row. */
	rowClassName?: string | ((record: T) => string | null);
	/** Color to mark each row with. */
	rowRibbonColor?: string | ((record: T) => string | null);
	/** Status of each row. Defaults no status. */
	rowStatus?: "highlighted" | ((record: T) => "highlighted" | null);
	/** Function that for each row determines what props should its `tr` element have based on the row's record. */
	onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, "key">;
	/** How tall should rows be. The default value is `"middle"`. */
	size?: "small" | "middle";
	/** An embedded table has no border around it and no background. This way it blends better into other components. */
	embedded?: boolean;
	loading?: boolean;
	pagination?: PaginationAuto | PaginationManual;
	expandable?: ExpandableConfig<T>;
	/** Whether the header should be shown. The default value is `true`. */
	showHeader?: boolean;
	/** Whether header titles should be uppercased. The default value is `true`. */
	uppercaseHeader?: boolean;
	/**
	 * By default sorting goes: 0. unsorted > 1. ascending > 2. descending > GOTO 0 (loop).
	 * With sorting cancellation disabled, GOTO 0 is replaced by GOTO 1. */
	disableSortingCancellation?: boolean;
	/** Sorting order to start with. */
	defaultSorting?: Sorting | null;
	/** Controlled sort order. */
	sorting?: Sorting | null;
	/** Sorting change handler for controlled sort order. */
	onSort?: (newSorting: Sorting | null) => void;
	/** How many skeleton rows should be used for the empty loading state. The default value is 1. */
	loadingSkeletonRows?: number;
	/** What to show when there's no data. */
	emptyState?: React.ReactNode;
	/** What to describe the entries as, singular and plural. The default value is `['entry', 'entries']`. */
	nouns?: [
		string,
		string
	];
	className?: string;
	style?: React.CSSProperties;
	"data-attr"?: string;
}
declare function LemonTable<T extends Record<string, any>>({ id, columns: rawColumns, dataSource, rowKey, rowClassName, rowRibbonColor, rowStatus, onRow, size, embedded, loading, pagination, expandable, showHeader, uppercaseHeader, disableSortingCancellation, defaultSorting, sorting, onSort, loadingSkeletonRows, emptyState, nouns, className, style, "data-attr": dataAttr, }: LemonTableProps<T>): JSX.Element;
declare type LemonTagPropsType = "warning" | "danger" | "success" | "default";
interface LemonTagProps extends React.HTMLAttributes<HTMLDivElement> {
	type?: LemonTagPropsType;
	children: JSX.Element | string;
	icon?: JSX.Element;
}
declare function LemonTag({ type, children, className, icon, ...props }: LemonTagProps): JSX.Element;
interface LemonTextAreaProps extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "defaultValue" | "onChange" | "prefix" | "suffix"> {
	ref?: React.Ref<HTMLTextAreaElement>;
	id?: string;
	value?: string;
	defaultValue?: string;
	placeholder?: string;
	onChange?: (newValue: string) => void;
	onPressEnter?: (newValue: string) => void;
	/** An embedded input has no border around it and no background. This way it blends better into other components. */
	embedded?: boolean;
	/** Whether there should be a clear icon to the right allowing you to reset the input. The `suffix` prop will be ignored if clearing is allowed. */
	allowClear?: boolean;
	/** Icon to prefix input field */
	icon?: React.ReactElement | null;
	/** Icon to suffix input field */
	sideIcon?: React.ReactElement | null;
	/** Whether input field is disabled */
	disabled?: boolean;
}
/** A `LemonRow`-based `textarea` component for multi-line text. */
declare const LemonTextArea: (props: LemonTextAreaProps & React.RefAttributes<HTMLTextAreaElement>) => React.ReactElement<any, string | React.JSXElementConstructor<any>> | null;
declare function ToastCloseButton({ closeToast }: {
	closeToast?: () => void;
}): JSX.Element;
interface ToastButton {
	label: string;
	action: () => void;
}
interface ToastOptionsWithButton extends ToastOptions {
	button?: ToastButton;
}
declare const GET_HELP_BUTTON: ToastButton;
interface ToastContentProps {
	type: "info" | "success" | "warning" | "error";
	message: string | JSX.Element;
	button?: ToastButton;
	id?: number | string;
}
declare function ToastContent({ type, message, button, id }: ToastContentProps): JSX.Element;
declare const lemonToast: {
	info(message: string | JSX.Element, { button, ...toastOptions }?: ToastOptionsWithButton): void;
	success(message: string | JSX.Element, { button, ...toastOptions }?: ToastOptionsWithButton): void;
	warning(message: string | JSX.Element, { button, ...toastOptions }?: ToastOptionsWithButton): void;
	error(message: string | JSX.Element, { button, ...toastOptions }?: ToastOptionsWithButton): void;
	dismiss(id?: string | number | undefined): void;
};
declare enum DashboardRestrictionLevel {
	EveryoneInProjectCanEdit = 21,
	OnlyCollaboratorsCanEdit = 37
}
declare enum DashboardPrivilegeLevel {
	CanView = 21,
	CanEdit = 37,
	/** This is not a value that can be set in the DB – it's inferred. */
	_ProjectAdmin = 888,
	/** This is not a value that can be set in the DB – it's inferred. */
	_Owner = 999
}
declare enum ShownAsValue {
	VOLUME = "Volume",
	STICKINESS = "Stickiness",
	LIFECYCLE = "Lifecycle"
}
declare const RETENTION_RECURRING = "retention_recurring";
declare const RETENTION_FIRST_TIME = "retention_first_time";
declare const ENTITY_MATCH_TYPE = "entities";
declare const PROPERTY_MATCH_TYPE = "properties";
declare enum FunnelLayout {
	horizontal = "horizontal",
	vertical = "vertical"
}
declare const BIN_COUNT_AUTO = "auto";
declare enum TaxonomicFilterGroupType {
	Actions = "actions",
	Cohorts = "cohorts",
	CohortsWithAllUsers = "cohorts_with_all",
	Elements = "elements",
	Events = "events",
	EventProperties = "event_properties",
	NumericalEventProperties = "numerical_event_properties",
	PersonProperties = "person_properties",
	PageviewUrls = "pageview_urls",
	Screens = "screens",
	CustomEvents = "custom_events",
	Wildcards = "wildcard",
	GroupsPrefix = "groups",
	Persons = "persons",
	FeatureFlags = "feature_flags",
	Insights = "insights",
	Experiments = "experiments",
	Plugins = "plugins",
	Dashboards = "dashboards",
	GroupNamesPrefix = "name_groups"
}
declare type BehavioralFilterType = BehavioralEventType | BehavioralCohortType | BehavioralLifecycleType;
declare enum BehavioralFilterKey {
	Behavioral = "behavioral",
	Cohort = "cohort",
	Person = "person"
}
declare enum LicensePlan {
	Scale = "scale",
	Enterprise = "enterprise"
}
interface UserBaseType {
	uuid: string;
	distinct_id: string;
	first_name: string;
	email: string;
}
interface UserBasicType extends UserBaseType {
	id: number;
}
interface ActionType {
	count?: number;
	created_at: string;
	deleted?: boolean;
	id: number;
	is_calculating?: boolean;
	last_calculated_at?: string;
	name: string | null;
	description?: string;
	post_to_slack?: boolean;
	slack_message_format?: string;
	steps?: ActionStepType[];
	created_by: UserBasicType | null;
	tags?: string[];
}
declare enum ActionStepUrlMatching {
	Contains = "contains",
	Regex = "regex",
	Exact = "exact"
}
interface ActionStepType {
	event?: string;
	href?: string | null;
	id?: number;
	name?: string;
	properties?: AnyPropertyFilter[];
	selector?: string | null;
	tag_name?: string;
	text?: string | null;
	url?: string | null;
	url_matching?: ActionStepUrlMatching;
	isNew?: string;
}
interface ElementType {
	attr_class?: string[];
	attr_id?: string;
	attributes: Record<string, string>;
	href: string;
	nth_child: number;
	nth_of_type: number;
	order: number;
	tag_name: string;
	text?: string;
}
declare type PropertyFilterValue = string | number | (string | number)[] | null;
interface PropertyFilter {
	key: string;
	operator: PropertyOperator | null;
	type: string;
	value: PropertyFilterValue;
	group_type_index?: number | null;
}
declare type EmptyPropertyFilter = Partial<PropertyFilter>;
declare type AnyPropertyFilter = PropertyFilter | EmptyPropertyFilter;
declare enum PropertyOperator {
	Exact = "exact",
	IsNot = "is_not",
	IContains = "icontains",
	NotIContains = "not_icontains",
	Regex = "regex",
	NotRegex = "not_regex",
	GreaterThan = "gt",
	GreaterThanOrEqual = "gte",
	LessThan = "lt",
	LessThanOrEqual = "lte",
	IsSet = "is_set",
	IsNotSet = "is_not_set",
	IsDateExact = "is_date_exact",
	IsDateBefore = "is_date_before",
	IsDateAfter = "is_date_after",
	Between = "between",
	NotBetween = "not_between",
	Minimum = "min",
	Maximum = "max"
}
declare type EntityType = "actions" | "events" | "new_entity";
interface Entity {
	id: string | number;
	name: string;
	custom_name?: string;
	order: number;
	type: EntityType;
}
declare type EntityFilter = {
	type?: EntityType;
	id: Entity["id"] | null;
	name: string | null;
	custom_name?: string;
	index?: number;
	order?: number;
};
interface FunnelStepRangeEntityFilter {
	funnel_from_step?: number;
	funnel_to_step?: number;
}
interface PersonType {
	id?: number;
	uuid?: string;
	name?: string;
	distinct_ids: string[];
	properties: Record<string, any>;
	created_at?: string;
	is_identified?: boolean;
}
interface MatchedRecordingEvents {
	uuid: string;
	window_id: string;
	timestamp: string;
}
interface MatchedRecording {
	session_id: string;
	events: MatchedRecordingEvents[];
}
interface CommonActorType {
	id?: string | number;
	properties: Record<string, any>;
	created_at?: string;
	matched_recordings?: MatchedRecording[];
}
interface PersonActorType extends CommonActorType {
	type: "person";
	uuid?: string;
	name?: string;
	distinct_ids: string[];
	is_identified: boolean;
}
interface GroupActorType extends CommonActorType {
	type: "group";
	group_key: string;
	group_type_index: number;
}
declare type ActorType = PersonActorType | GroupActorType;
interface CohortGroupType {
	id: string;
	days?: string;
	action_id?: number;
	event_id?: string;
	label?: string;
	count?: number;
	count_operator?: string;
	properties?: AnyPropertyFilter[];
	matchType: MatchType;
	name?: string;
}
interface CohortCriteriaType {
	id: string;
	key: string;
	value: BehavioralFilterType;
	type: BehavioralFilterKey;
	operator?: PropertyOperator | null;
	group_type_index?: number | null;
	event_type?: TaxonomicFilterGroupType | null;
	operator_value?: PropertyFilterValue;
	time_value?: number | string | null;
	time_interval?: TimeUnitType | null;
	total_periods?: number | null;
	min_periods?: number | null;
	seq_event_type?: TaxonomicFilterGroupType | null;
	seq_event?: string | number | null;
	seq_time_value?: number | string | null;
	seq_time_interval?: TimeUnitType | null;
	negation?: boolean;
	value_property?: string | null;
}
declare type EmptyCohortCriteriaType = Partial<CohortCriteriaType>;
declare type AnyCohortCriteriaType = CohortCriteriaType | EmptyCohortCriteriaType;
declare type MatchType = typeof ENTITY_MATCH_TYPE | typeof PROPERTY_MATCH_TYPE;
interface CohortType {
	count?: number;
	description?: string;
	created_by?: UserBasicType | null;
	created_at?: string;
	deleted?: boolean;
	id: number | "new";
	is_calculating?: boolean;
	errors_calculating?: number;
	last_calculation?: string;
	is_static?: boolean;
	name?: string;
	csv?: UploadFile;
	groups: CohortGroupType[];
	filters: {
		properties: CohortCriteriaGroupFilter;
	};
}
declare type BinCountValue = number | typeof BIN_COUNT_AUTO;
declare enum StepOrderValue {
	STRICT = "strict",
	UNORDERED = "unordered",
	ORDERED = "ordered"
}
interface EventType {
	elements: ElementType[];
	elements_hash: string | null;
	elements_chain?: string | null;
	id: number | string;
	properties: Record<string, any>;
	timestamp: string;
	colonTimestamp?: string;
	person?: Partial<PersonType> | null;
	event: string;
}
declare type InsightShortId = string & {
	readonly "": unique symbol;
};
declare enum InsightColor {
	White = "white",
	Black = "black",
	Blue = "blue",
	Green = "green",
	Purple = "purple"
}
interface DashboardTile {
	result: any | null;
	layouts: Record<string, any>;
	color: InsightColor | null;
	last_refresh: string | null;
	filters: Partial<FilterType>;
	filters_hash: string;
}
interface InsightModel extends DashboardTile {
	/** The unique key we use when communicating with the user, e.g. in URLs */
	short_id: InsightShortId;
	/** The primary key in the database, used as well in API endpoints */
	id: number;
	name: string;
	derived_name?: string;
	description?: string;
	favorited?: boolean;
	order: number | null;
	deleted: boolean;
	saved: boolean;
	created_at: string;
	created_by: UserBasicType | null;
	refreshing: boolean;
	is_sample: boolean;
	dashboards: number[] | null;
	updated_at: string;
	tags?: string[];
	last_modified_at: string;
	last_modified_by: UserBasicType | null;
	effective_restriction_level: DashboardRestrictionLevel;
	effective_privilege_level: DashboardPrivilegeLevel;
	timezone?: string;
	/** Only used in the frontend to store the next breakdown url */
	next?: string;
}
interface DashboardType {
	id: number;
	name: string;
	description: string;
	pinned: boolean;
	items: InsightModel[];
	created_at: string;
	created_by: UserBasicType | null;
	is_shared: boolean;
	share_token: string;
	deleted: boolean;
	filters: Record<string, any>;
	creation_mode: "default" | "template" | "duplicate";
	restriction_level: DashboardRestrictionLevel;
	effective_restriction_level: DashboardRestrictionLevel;
	effective_privilege_level: DashboardPrivilegeLevel;
	tags?: string[];
	/** Purely local value to determine whether the dashboard should be highlighted, e.g. as a fresh duplicate. */
	_highlight?: boolean;
}
/** Explicit dashboard collaborator, based on DashboardPrivilege. */
interface DashboardCollaboratorType {
	id: string;
	dashboard_id: DashboardType["id"];
	user: UserBasicType;
	level: DashboardPrivilegeLevel;
	added_at: string;
	updated_at: string;
}
declare enum PluginLogEntryType {
	Debug = "DEBUG",
	Log = "LOG",
	Info = "INFO",
	Warn = "WARN",
	Error = "ERROR"
}
interface PluginLogEntry {
	id: string;
	team_id: number;
	plugin_id: number;
	plugin_config_id: number;
	timestamp: string;
	type: PluginLogEntryType;
	is_system: boolean;
	message: string;
	instance_id: string;
}
declare enum ChartDisplayType {
	ActionsLineGraph = "ActionsLineGraph",
	ActionsLineGraphCumulative = "ActionsLineGraphCumulative",
	ActionsTable = "ActionsTable",
	ActionsPie = "ActionsPie",
	ActionsBar = "ActionsBar",
	ActionsBarValue = "ActionsBarValue",
	PathsViz = "PathsViz",
	FunnelViz = "FunnelViz",
	WorldMap = "WorldMap"
}
declare type BreakdownType = "cohort" | "person" | "event" | "group";
declare type IntervalType = "hour" | "day" | "week" | "month";
declare enum InsightType {
	TRENDS = "TRENDS",
	STICKINESS = "STICKINESS",
	LIFECYCLE = "LIFECYCLE",
	FUNNELS = "FUNNELS",
	RETENTION = "RETENTION",
	PATHS = "PATHS"
}
declare enum PathType {
	PageView = "$pageview",
	Screen = "$screen",
	CustomEvent = "custom_event"
}
declare enum FunnelPathType {
	before = "funnel_path_before_step",
	between = "funnel_path_between_steps",
	after = "funnel_path_after_step"
}
declare enum FunnelVizType {
	Steps = "steps",
	TimeToConvert = "time_to_convert",
	Trends = "trends"
}
declare type RetentionType = typeof RETENTION_RECURRING | typeof RETENTION_FIRST_TIME;
declare type BreakdownKeyType = string | number | (string | number)[] | null;
interface Breakdown {
	property: string | number;
	type: BreakdownType;
}
interface FilterType {
	insight?: InsightType;
	display?: ChartDisplayType;
	interval?: IntervalType;
	smoothing_intervals?: number;
	date_from?: string | null;
	date_to?: string | null;
	properties?: AnyPropertyFilter[] | PropertyGroupFilter;
	events?: Record<string, any>[];
	event?: string;
	actions?: Record<string, any>[];
	breakdown_type?: BreakdownType | null;
	breakdown?: BreakdownKeyType;
	breakdowns?: Breakdown[];
	breakdown_value?: string | number;
	breakdown_group_type_index?: number | null;
	shown_as?: ShownAsValue;
	session?: string;
	period?: string;
	retention_type?: RetentionType;
	retention_reference?: "total" | "previous";
	total_intervals?: number;
	new_entity?: Record<string, any>[];
	returning_entity?: Record<string, any>;
	target_entity?: Record<string, any>;
	path_type?: PathType;
	include_event_types?: PathType[];
	start_point?: string;
	end_point?: string;
	path_groupings?: string[];
	stickiness_days?: number;
	type?: EntityType;
	entity_id?: string | number;
	entity_type?: EntityType;
	entity_math?: string;
	people_day?: any;
	people_action?: any;
	formula?: any;
	filter_test_accounts?: boolean;
	from_dashboard?: boolean | number;
	layout?: FunnelLayout;
	funnel_step?: number;
	entrance_period_start?: string;
	drop_off?: boolean;
	funnel_viz_type?: FunnelVizType;
	funnel_from_step?: number;
	funnel_to_step?: number;
	funnel_step_breakdown?: string | number[] | number | null;
	compare?: boolean;
	bin_count?: BinCountValue;
	funnel_window_interval_unit?: FunnelConversionWindowTimeUnit;
	funnel_window_interval?: number | undefined;
	funnel_order_type?: StepOrderValue;
	exclusions?: FunnelStepRangeEntityFilter[];
	exclude_events?: string[];
	step_limit?: number;
	path_start_key?: string;
	path_end_key?: string;
	path_dropoff_key?: string;
	path_replacements?: boolean;
	local_path_cleaning_filters?: Record<string, any>[];
	funnel_filter?: Record<string, any>;
	funnel_paths?: FunnelPathType;
	edge_limit?: number | undefined;
	min_edge_weight?: number | undefined;
	max_edge_weight?: number | undefined;
	funnel_correlation_person_entity?: Record<string, any>;
	funnel_correlation_person_converted?: "true" | "false";
	funnel_custom_steps?: number[];
	aggregation_group_type_index?: number | undefined;
	funnel_advanced?: boolean;
	show_legend?: boolean;
	hidden_legend_keys?: Record<string, boolean | undefined>;
}
interface ActionFilter extends EntityFilter {
	math?: string;
	math_property?: string;
	math_group_type_index?: number | null;
	properties?: PropertyFilter[];
	type: EntityType;
}
declare enum FunnelConversionWindowTimeUnit {
	Minute = "minute",
	Hour = "hour",
	Day = "day",
	Week = "week",
	Month = "month"
}
interface LicenseType {
	id: number;
	key: string;
	plan: LicensePlan;
	valid_until: string;
	max_users: number | null;
	created_at: string;
}
interface EventDefinition {
	id: string;
	name: string;
	description: string;
	tags?: string[];
	volume_30_day: number | null;
	query_usage_30_day: number | null;
	owner?: UserBasicType | null;
	created_at?: string;
	last_seen_at?: string;
	updated_at?: string;
	updated_by?: UserBasicType | null;
	verified?: boolean;
	verified_at?: string;
	verified_by?: string;
}
declare enum PropertyType {
	DateTime = "DateTime",
	String = "String",
	Numeric = "Numeric",
	Boolean = "Boolean"
}
interface PropertyDefinition {
	id: string;
	name: string;
	description: string;
	tags?: string[];
	volume_30_day: number | null;
	query_usage_30_day: number | null;
	updated_at?: string;
	updated_by?: UserBasicType | null;
	is_numerical?: boolean;
	is_event_property?: boolean;
	property_type?: PropertyType;
	created_at?: string;
	last_seen_at?: string;
	example?: string;
}
declare enum FilterLogicalOperator {
	And = "AND",
	Or = "OR"
}
interface PropertyGroupFilter {
	type: FilterLogicalOperator;
	values: PropertyGroupFilterValue[];
}
interface PropertyGroupFilterValue {
	type: FilterLogicalOperator;
	values: AnyPropertyFilter[];
}
interface CohortCriteriaGroupFilter {
	id?: string;
	type: FilterLogicalOperator;
	values: AnyCohortCriteriaType[] | CohortCriteriaGroupFilter[];
}
declare enum BehavioralEventType {
	PerformEvent = "performed_event",
	PerformMultipleEvents = "performed_event_multiple",
	PerformSequenceEvents = "performed_event_sequence",
	NotPerformedEvent = "not_performed_event",
	NotPerformSequenceEvents = "not_performed_event_sequence",
	HaveProperty = "have_property",
	NotHaveProperty = "not_have_property"
}
declare enum BehavioralCohortType {
	InCohort = "in_cohort",
	NotInCohort = "not_in_cohort"
}
declare enum BehavioralLifecycleType {
	PerformEventFirstTime = "performed_event_first_time",
	PerformEventRegularly = "performed_event_regularly",
	StopPerformEvent = "stopped_performing_event",
	StartPerformEventAgain = "restarted_performing_event"
}
declare enum TimeUnitType {
	Day = "day",
	Week = "week",
	Month = "month",
	Year = "year"
}
declare function AdHocInsight({ filters, style, }: {
	filters: Partial<FilterType>;
	style: React.CSSProperties;
}): JSX.Element;
declare type RoutePart = string | Record<string, any>;
interface LinkProps extends React.HTMLProps<HTMLAnchorElement> {
	to?: string | [
		string,
		RoutePart?,
		RoutePart?
	];
	preventClick?: boolean;
	tag?: string | React.FunctionComponentElement<any>;
}
declare function Link({ to, preventClick, tag, ...props }: LinkProps): JSX.Element;
interface PeopleParamType {
	action?: ActionFilter;
	label: string;
	date_to?: string | number;
	date_from?: string | number;
	breakdown_value?: string | number;
	target_date?: number | string;
	lifecycle_type?: string | number;
}
interface PersonFilters {
	properties?: AnyPropertyFilter[];
	search?: string;
	cohort?: number;
}
interface ActivityChange {
	type: "FeatureFlag" | "Person" | "Insight";
	action: "changed" | "created" | "deleted";
	field?: string;
	before?: string | Record<string, any> | boolean;
	after?: string | Record<string, any> | boolean;
}
interface PersonMerge {
	type: "Person";
	source: PersonType[];
	target: PersonType;
}
interface ActivityLogDetail {
	merge: PersonMerge | null;
	changes: ActivityChange[] | null;
	name: string | null;
	short_id?: InsightShortId | null;
}
interface ActivityUser {
	email: string;
	first_name: string;
}
declare enum ActivityScope {
	FEATURE_FLAG = "FeatureFlag",
	PERSON = "Person",
	INSIGHT = "Insight"
}
interface ActivityLogItem {
	user: ActivityUser;
	activity: string;
	created_at: string;
	scope: ActivityScope;
	item_id?: string;
	detail: ActivityLogDetail;
}
declare type Describer = (logItem: ActivityLogItem) => string | JSX.Element | null;
interface ActivityLogProps {
	scope: ActivityScope;
	id?: number;
	describer?: Describer;
	startingPage?: number;
	caption?: string | JSX.Element;
}
interface PaginatedResponse<T> {
	results: T[];
	next?: string;
	previous?: string;
}
interface CountedPaginatedResponse extends PaginatedResponse<ActivityLogItem> {
	total_count: number;
}
declare const api: {
	actions: {
		get(actionId: number): Promise<ActionType$1>;
		create(actionData: Partial<ActionType$1>, temporaryToken?: string | undefined): Promise<ActionType$1>;
		update(actionId: number, actionData: Partial<ActionType$1>, temporaryToken?: string | undefined): Promise<ActionType$1>;
		list(params?: string | undefined): Promise<PaginatedResponse$1<ActionType$1>>;
		getPeople(peopleParams: PeopleParamType$1, filters: Partial<FilterType$1>, searchTerm?: string | undefined): Promise<PaginatedResponse$1<{
			people: ActorType$1[];
			count: number;
		}>>;
		getCount(actionId: number): Promise<number>;
		determineDeleteEndpoint(): string;
		determinePeopleCsvUrl(peopleParams: PeopleParamType$1, filters: Partial<FilterType$1>): string;
	};
	activity: {
		list(activityLogProps: ActivityLogProps$1, page?: number, teamId?: number): Promise<CountedPaginatedResponse$1>;
	};
	exports: {
		determineExportUrl(exportId: number, teamId?: number): string;
	};
	events: {
		get(id: string | number, includePerson?: boolean, teamId?: number): Promise<EventType$1>;
		list(filters: Partial<FilterType$1>, limit?: number, teamId?: number): Promise<PaginatedResponse$1<EventType$1[]>>;
		determineListEndpoint(filters: Partial<FilterType$1>, limit?: number, teamId?: number): string;
	};
	eventDefinitions: {
		list({ limit, teamId, ...params }: {
			order_ids_first?: string[] | undefined;
			excluded_ids?: string[] | undefined;
			limit?: number | undefined;
			offset?: number | undefined;
			teamId?: number | undefined;
		}): Promise<PaginatedResponse$1<EventDefinition$1>>;
		determineListEndpoint({ limit, teamId, ...params }: {
			order_ids_first?: string[] | undefined;
			excluded_ids?: string[] | undefined;
			limit?: number | undefined;
			offset?: number | undefined;
			teamId?: number | undefined;
		}): string;
	};
	propertyDefinitions: {
		list({ limit, teamId, ...params }: {
			event_names?: string[] | undefined;
			order_ids_first?: string[] | undefined;
			excluded_ids?: string[] | undefined;
			excluded_properties?: string[] | undefined;
			is_event_property?: boolean | undefined;
			limit?: number | undefined;
			offset?: number | undefined;
			teamId?: number | undefined;
		}): Promise<PaginatedResponse$1<PropertyDefinition$1>>;
		determineListEndpoint({ limit, teamId, ...params }: {
			event_names?: string[] | undefined;
			order_ids_first?: string[] | undefined;
			excluded_ids?: string[] | undefined;
			excluded_properties?: string[] | undefined;
			is_event_property?: boolean | undefined;
			limit?: number | undefined;
			offset?: number | undefined;
			teamId?: number | undefined;
		}): string;
	};
	cohorts: {
		get(cohortId: number | "new"): Promise<CohortType$1>;
		create(cohortData: Partial<CohortType$1>, filterParams?: string | undefined): Promise<CohortType$1>;
		update(cohortId: number | "new", cohortData: Partial<CohortType$1>, filterParams?: string | undefined): Promise<CohortType$1>;
		list(): Promise<PaginatedResponse$1<CohortType$1>>;
		determineDeleteEndpoint(): string;
	};
	dashboards: {
		collaborators: {
			list(dashboardId: number): Promise<DashboardCollaboratorType$1[]>;
			create(dashboardId: number, userUuid: string, level: DashboardPrivilegeLevel$1): Promise<DashboardCollaboratorType$1>;
			delete(dashboardId: number, userUuid: string): Promise<void>;
		};
	};
	person: {
		determineCSVUrl(filters: PersonFilters$1): string;
	};
	pluginLogs: {
		search(pluginConfigId: number, currentTeamId: number | null, searchTerm?: string | null, typeFilters?: antd_lib_checkbox_Group.CheckboxValueType[], trailingEntry?: PluginLogEntry$1 | null, leadingEntry?: PluginLogEntry$1 | null): Promise<PluginLogEntry$1[]>;
	};
	licenses: {
		get(licenseId: number): Promise<LicenseType$1>;
		list(): Promise<PaginatedResponse$1<LicenseType$1>>;
		create(key: string): Promise<LicenseType$1>;
		delete(licenseId: number): Promise<LicenseType$1>;
	};
	get(url: string, signal?: AbortSignal | undefined): Promise<any>;
	update(url: string, data: any): Promise<any>;
	create(url: string, data?: any): Promise<any>;
	delete(url: string): Promise<any>;
};

export { ActionFilter, ActionStepType, ActionType, ActivityChange, ActivityLogDetail, ActivityLogItem, ActivityLogProps, ActivityUser, ActorType, AdHocInsight, AnyCohortCriteriaType, AnyPropertyFilter, BehavioralFilterType, BinCountValue, BoxCSSProperties, Breakdown, BreakdownKeyType, BreakdownType, CohortCriteriaGroupFilter, CohortCriteriaType, CohortGroupType, CohortType, CommonActorType, CountedPaginatedResponse, DashboardCollaboratorType, DashboardTile, DashboardType, Describer, ElementType, EmptyCohortCriteriaType, EmptyPropertyFilter, Entity, EntityFilter, EntityType, EventDefinition, EventType, ExpandableConfig, FilterType, FunnelStepRangeEntityFilter, GET_HELP_BUTTON, GroupActorType, InsightModel, InsightShortId, IntervalType, LemonBubble, LemonBubbleProps, LemonButton, LemonButtonPopup, LemonButtonProps, LemonButtonPropsBase, LemonButtonWithPopup, LemonButtonWithPopupProps, LemonButtonWithSideAction, LemonButtonWithSideActionProps, LemonCheckbox, LemonCheckboxProps, LemonDivider, LemonDividerProps, LemonInput, LemonInputProps, LemonModal, LemonModalProps, LemonRow, LemonRowProps, LemonRowPropsBase, LemonSelect, LemonSelectOption, LemonSelectOptions, LemonSelectProps, LemonSwitch, LemonSwitchProps, LemonTable, LemonTableColumn, LemonTableColumnGroup, LemonTableColumns, LemonTableProps, LemonTag, LemonTagProps, LemonTagPropsType, LemonTextArea, LemonTextAreaProps, LicenseType, Link, LinkProps, MatchType, MatchedRecording, MatchedRecordingEvents, PaginatedResponse, PaginationAuto, PaginationBase, PaginationManual, PeopleParamType, PersonActorType, PersonFilters, PersonMerge, PersonType, PluginLogEntry, PopupProps, PropertyDefinition, PropertyFilter, PropertyFilterValue, PropertyGroupFilter, PropertyGroupFilterValue, RetentionType, RoutePart, SideAction, Sorting, TableCellRenderResult, TableCellRepresentation, ToastButton, ToastCloseButton, ToastContent, ToastContentProps, ToastOptionsWithButton, UserBaseType, UserBasicType, api, lemonToast };
