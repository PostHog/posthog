export { BreakdownFilter } from './TaxonomicBreakdownFilter'

export const isURLNormalizeable = (propertyName: string): boolean => {
    return ['$current_url', '$pathname'].includes(propertyName)
}
