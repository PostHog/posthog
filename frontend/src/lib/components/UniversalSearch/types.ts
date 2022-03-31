import { LogicWrapper } from 'kea'
import { PluginSelectionType } from 'scenes/plugins/pluginsLogic'
import {
    ActionType,
    CohortType,
    EventDefinition,
    Experiment,
    FeatureFlagType,
    Group,
    InsightModel,
    PersonType,
} from '~/types'
import { SimpleOption, TaxonomicFilterValue } from '../TaxonomicFilter/types'

export interface UniversalSearchLogicProps extends UniversalSearchProps {
    universalSearchLogicKey: string
}

export interface SearchListLogicProps extends UniversalSearchLogicProps {
    listGroupType: UniversalSearchGroupType
}

export type SearchDefinitionTypes =
    | EventDefinition
    | CohortType
    | ActionType
    | Experiment
    | PersonType
    | Group
    | FeatureFlagType
    | InsightModel
    | PluginSelectionType

export interface ListStorage {
    results: SearchDefinitionTypes[]
    searchQuery?: string // Query used for the results currently in state
    count: number
    expandedCount?: number
    queryChanged?: boolean
    first?: boolean
}

export interface UniversalSearchProps {
    groupType?: UniversalSearchGroupType
    value?: TaxonomicFilterValue
    onChange?: (group: UniversalSearchGroup, value: TaxonomicFilterValue, item: any) => void
    onClose?: () => void
    searchGroupTypes: UniversalSearchGroupType[]
    universalSearchFilterLogicKey?: string
    optionsFromProp?: Partial<Record<UniversalSearchGroupType, SimpleOption[]>>
    height?: number
    width?: number
    popoverEnabled?: boolean
    selectFirstItem?: boolean
}

export enum UniversalSearchGroupType {
    Actions = 'actions',
    Cohorts = 'cohorts',
    // CohortsWithAllUsers = 'cohorts_with_all',
    // Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
    NumericalEventProperties = 'numerical_event_properties',
    Persons = 'persons',
    // PersonProperties = 'person_properties',
    // PageviewUrls = 'pageview_urls',
    // Screens = 'screens',
    // CustomEvents = 'custom_events',
    // Wildcards = 'wildcard',
    GroupsPrefix = 'groups',
    FeatureFlags = 'feature_flags',
    Insights = 'insights',
    Experiments = 'experiments',
    Plugins = 'plugins',
    Dashboards = 'dashboards',
}

export interface UniversalSearchGroup {
    name: string
    searchPlaceholder: string
    type: UniversalSearchGroupType
    endpoint?: string
    /** If present, will be used instead of "endpoint" until the user presses "expand results". */
    scopedEndpoint?: string
    expandLabel?: (props: { count: number; expandedCount: number }) => React.ReactNode
    options?: Record<string, any>[]
    logic?: LogicWrapper
    value?: string
    searchAlias?: string
    valuesEndpoint?: (key: string) => string
    getName: (instance: any) => string
    getValue: (instance: any) => TaxonomicFilterValue
    // getPopupHeader: (instance: any) => string
    // getIcon?: (instance: any) => JSX.Element
    groupTypeIndex?: number
    getFullDetailUrl?: (instance: any) => string
}
