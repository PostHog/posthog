export const actionScopeToName: Record<string, string> = {
    global: 'Global',
    insights: 'Insights',
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
}

export const tabToName: Record<Tab, string> = {
    [Tab.All]: 'All',
    [Tab.Action]: 'Actions',
    [Tab.Cohort]: 'Cohorts',
    [Tab.Dashboard]: 'Dashboards',
    [Tab.EventDefinition]: 'Event definitions',
    [Tab.Experiment]: 'Experiments',
    [Tab.FeatureFlag]: 'Feature flags',
    [Tab.Insight]: 'Insights',
    [Tab.Notebook]: 'Notebooks',
    [Tab.Person]: 'Persons',
}
