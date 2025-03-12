import { PropertyIconStandalone } from './PropertyIconStandalone'
import { PropertyIconWithLabel } from './PropertyIconWithLabel'

export { PROPERTIES_ICON_MAP } from './PropertyIconStandalone'
export type { PropertyIconProps } from './types'

export const PropertyIcon = Object.assign(PropertyIconStandalone, {
    WithLabel: PropertyIconWithLabel,
})
