// Auto-generated with kea-typegen. DO NOT EDIT!

export interface insightHistoryLogicType<InsightHistory> {
    key: any
    actionCreators: {
        loadInsights: () => {
            type: 'load insights (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: any
        }
        loadInsightsSuccess: (
            insights: InsightHistory[]
        ) => {
            type: 'load insights success (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: {
                insights: InsightHistory[]
            }
        }
        loadInsightsFailure: (
            error: string
        ) => {
            type: 'load insights failure (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load insights (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadInsights'
        'load insights success (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadInsightsSuccess'
        'load insights failure (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)': 'loadInsightsFailure'
    }
    actionTypes: {
        loadInsights: 'load insights (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadInsightsSuccess: 'load insights success (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
        loadInsightsFailure: 'load insights failure (frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic)'
    }
    actions: {
        loadInsights: () => void
        loadInsightsSuccess: (insights: InsightHistory[]) => void
        loadInsightsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'insights', 'InsightHistoryPanel', 'insightHistoryLogic']
    pathString: 'frontend.src.scenes.insights.InsightHistoryPanel.insightHistoryLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        insights: InsightHistory[]
        insightsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        insights: (state: InsightHistory[], action: any, fullState: any) => InsightHistory[]
        insightsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        insights: InsightHistory[]
        insightsLoading: boolean
    }
    selectors: {
        insights: (state: any, props: any) => InsightHistory[]
        insightsLoading: (state: any, props: any) => boolean
    }
    values: {
        insights: InsightHistory[]
        insightsLoading: boolean
    }
    _isKea: true
}
