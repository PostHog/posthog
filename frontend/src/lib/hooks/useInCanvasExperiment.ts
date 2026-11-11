import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export const useInCanvasExperiment = (): boolean => {
    const canvasExperiment = useFeatureFlag('CANVAS_EXPERIMENT')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    return canvasExperiment && todayRailNav
}
