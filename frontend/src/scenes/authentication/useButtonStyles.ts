import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function useButtonStyle(): Record<string, any> {
    const is3000 = useFeatureFlag('POSTHOG_3000', 'test')

    return is3000
        ? {
              status: 'primary-alt',
              size: 'large',
          }
        : {
              status: 'primary',
              size: 'medium',
          }
}
