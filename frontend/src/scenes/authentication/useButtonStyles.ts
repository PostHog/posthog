import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function useButtonStyle(): Record<string, any> {
    const is3000 = useFeatureFlag('POSTHOG_3000')

    return is3000
        ? {
              size: 'large',
          }
        : {
              size: 'medium',
          }
}
