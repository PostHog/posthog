import { useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function useButtonStyle(): Record<string, any> {
    const { is3000 } = useValues(themeLogic)

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
