export type DashboardTemplateChooserExperimentVariant = 'control' | 'simple' | 'new'

export function resolveDashboardTemplateChooserExperimentVariant(
    flagValue: string | boolean | undefined
): DashboardTemplateChooserExperimentVariant {
    if (flagValue === 'simple' || flagValue === 'new' || flagValue === 'control') {
        return flagValue
    }
    return 'new'
}
