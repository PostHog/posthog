export interface DashboardUnsavedChangesAction {
    key: 'discard' | 'preview' | 'save'
    label: string
    dataAttr: string
    disabledReason: string | undefined
    tooltip: string
    onClick: () => void
    loading: boolean
}

export interface DashboardUnsavedChangesActionsInput {
    layoutEditMode: boolean
    canEditDashboard: boolean
    showApplyFiltersBanner: boolean
    loadingPreview: boolean
    dashboardFiltersSaving: boolean
    discard: () => void
    preview: () => void
    save: () => void
}

export function dashboardUnsavedChangesActions({
    layoutEditMode,
    canEditDashboard,
    showApplyFiltersBanner,
    loadingPreview,
    dashboardFiltersSaving,
    discard,
    preview,
    save,
}: DashboardUnsavedChangesActionsInput): DashboardUnsavedChangesAction[] {
    return [
        {
            key: 'discard',
            label: 'Discard',
            dataAttr: layoutEditMode ? 'dashboard-discard-filters' : 'dashboard-edit-mode-discard',
            disabledReason: dashboardFiltersSaving ? 'Dashboard filters are saving' : undefined,
            tooltip: 'Restore the settings saved to this dashboard.',
            onClick: discard,
            loading: false,
        },
        ...(showApplyFiltersBanner
            ? [
                  {
                      key: 'preview' as const,
                      label: loadingPreview ? 'Previewing' : 'Preview',
                      dataAttr: 'dashboard-apply-filters',
                      disabledReason: loadingPreview ? 'Previewing unsaved filters' : undefined,
                      tooltip: 'Update the dashboard data with these unsaved filters. This does not save them.',
                      onClick: preview,
                      loading: false,
                  },
              ]
            : []),
        ...(canEditDashboard
            ? [
                  {
                      key: 'save' as const,
                      label: 'Save filters',
                      dataAttr: 'dashboard-save-filters',
                      disabledReason: undefined,
                      tooltip: 'Save these changes as the dashboard default.',
                      onClick: save,
                      loading: dashboardFiltersSaving,
                  },
              ]
            : []),
    ]
}
