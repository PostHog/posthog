export interface AutoRefreshState {
  autoRefreshIfEmpty: boolean;
  installationId: string | null;
  isLoading: boolean;
  toolsLength: number;
  alreadyRefreshed: boolean;
  refreshPending: boolean;
}

export function shouldAutoRefreshTools(state: AutoRefreshState): boolean {
  if (!state.autoRefreshIfEmpty) return false;
  if (!state.installationId) return false;
  if (state.isLoading) return false;
  if (state.toolsLength > 0) return false;
  if (state.alreadyRefreshed) return false;
  if (state.refreshPending) return false;
  return true;
}
