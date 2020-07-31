// Auto-generated with kea-typegen. DO NOT EDIT!

export interface insightHistoryLogicType<InsightHistory> {
    key: any
    actionCreators: {
        loadInsights: () => {
            type: 'load insights (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: any
        }
        loadInsightsSuccess: (
            insights: InsightHistory[]
        ) => {
            type: 'load insights success (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: {
                insights: InsightHistory[]
            }
        }
        loadInsightsFailure: (
            error: string
        ) => {
            type: 'load insights failure (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: {
                error: string
            }
        }
        loadSavedInsights: () => {
            type: 'load saved insights (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: any
        }
        loadSavedInsightsSuccess: (
            savedInsights: InsightHistory[]
        ) => {
            type: 'load saved insights success (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: {
                savedInsights: InsightHistory[]
            }
        }
        loadSavedInsightsFailure: (
            error: string
        ) => {
            type: 'load saved insights failure (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: {
                error: string
            }
        }
        createInsight: (
            filters: Record<string, any>
        ) => {
            type: 'create insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: { filters: Record<string, any> }
        }
        saveInsight: (
            id: number,
            name: string
        ) => {
            type: 'save insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: { id: number; name: string }
        }
        deleteInsight: (
            insight: InsightHistory
        ) => {
            type: 'delete insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: { insight: InsightHistory }
        }
    }
    actionKeys: {
        'load insights (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadInsights'
        'load insights success (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadInsightsSuccess'
        'load insights failure (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadInsightsFailure'
        'load saved insights (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadSavedInsights'
        'load saved insights success (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadSavedInsightsSuccess'
        'load saved insights failure (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadSavedInsightsFailure'
        'create insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'createInsight'
        'save insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'saveInsight'
        'delete insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'deleteInsight'
    }
    actionTypes: {
        loadInsights: 'load insights (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadInsightsSuccess: 'load insights success (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadInsightsFailure: 'load insights failure (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadSavedInsights: 'load saved insights (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadSavedInsightsSuccess: 'load saved insights success (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadSavedInsightsFailure: 'load saved insights failure (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        createInsight: 'create insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        saveInsight: 'save insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        deleteInsight: 'delete insight (scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
    }
    actions: {
        loadInsights: () => void
        loadInsightsSuccess: (insights: InsightHistory[]) => void
        loadInsightsFailure: (error: string) => void
        loadSavedInsights: () => void
        loadSavedInsightsSuccess: (savedInsights: InsightHistory[]) => void
        loadSavedInsightsFailure: (error: string) => void
        createInsight: (filters: Record<string, any>) => void
        saveInsight: (id: number, name: string) => void
        deleteInsight: (insight: InsightHistory) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'insights', 'InsightHistoryPanel', 'insightHistoryLogic']
    pathString: 'scenes.insights.InsightHistoryPanel.insightHistoryLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        insights: InsightHistory[]
        insightsLoading: boolean
        savedInsights: InsightHistory[]
        savedInsightsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        insights: (state: InsightHistory[], action: any, fullState: any) => InsightHistory[]
        insightsLoading: (state: boolean, action: any, fullState: any) => boolean
        savedInsights: (state: InsightHistory[], action: any, fullState: any) => InsightHistory[]
        savedInsightsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        insights: InsightHistory[]
        insightsLoading: boolean
        savedInsights: InsightHistory[]
        savedInsightsLoading: boolean
    }
    selectors: {
        insights: (state: any, props: any) => InsightHistory[]
        insightsLoading: (state: any, props: any) => boolean
        savedInsights: (state: any, props: any) => InsightHistory[]
        savedInsightsLoading: (state: any, props: any) => boolean
    }
    values: {
        insights: InsightHistory[]
        insightsLoading: boolean
        savedInsights: InsightHistory[]
        savedInsightsLoading: boolean
    }
    _isKea: true
}
