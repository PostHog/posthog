import { useFeatureFlag } from './useFeatureFlag'
import { useWindowSize } from './useWindowSize'

export function useApmMobileLayout(): boolean {
    const enabled = useFeatureFlag('APM_MOBILE_TRIAGE')
    const { isWindowLessThan } = useWindowSize()
    return enabled && isWindowLessThan('lg')
}
