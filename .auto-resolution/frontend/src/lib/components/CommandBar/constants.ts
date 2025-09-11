export const actionScopeToName: Record<string, string> = {
    global: 'Global',
    insights: 'Insights',
}

export enum TabGroup {
    All = 'all',
    EventData = 'event_data',
    PostHog = 'posthog',
    Products = 'products',
}

export const groupToName: Record<TabGroup, string | null> = {
    [TabGroup.All]: 'All',
    [TabGroup.EventData]: 'Event data',
    [TabGroup.PostHog]: 'PostHog',
    [TabGroup.Products]: 'Products',
}

export enum Tab {
    All = 'all',
    Action = 'action',
    Cohort = 'cohort',
    Dashboard = 'dashboard',
    EventDefinition = 'event_definition',
    Experiment = 'experiment',
    FeatureFlag = 'feature_flag',
    Insight = 'insight',
    Notebook = 'notebook',
    Person = 'person',
    Group0 = 'group_0',
    Group1 = 'group_1',
    Group2 = 'group_2',
    Group3 = 'group_3',
    Group4 = 'group_4',
    Survey = 'survey',
    Products = 'products',
}

export const clickhouseTabs = [Tab.Person, Tab.Group0, Tab.Group1, Tab.Group2, Tab.Group3, Tab.Group4]

export const tabToName: Record<Tab, string | null> = {
    [Tab.All]: 'All',
    [Tab.Action]: 'Actions',
    [Tab.Cohort]: 'Cohorts',
    [Tab.Dashboard]: 'Dashboards',
    [Tab.EventDefinition]: 'Events',
    [Tab.Experiment]: 'Experiments',
    [Tab.FeatureFlag]: 'Feature flags',
    [Tab.Insight]: 'Insights',
    [Tab.Notebook]: 'Notebooks',
    [Tab.Person]: 'Persons',
    [Tab.Group0]: null,
    [Tab.Group1]: null,
    [Tab.Group2]: null,
    [Tab.Group3]: null,
    [Tab.Group4]: null,
    [Tab.Survey]: 'Surveys',
    [Tab.Products]: 'Products',
}
