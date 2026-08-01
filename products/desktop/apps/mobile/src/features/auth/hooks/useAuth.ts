import { useAuthStore } from "../stores/authStore";

/**
 * A convenience hook for accessing common auth state and methods.
 */
export function useAuth() {
  const {
    isAuthenticated,
    isLoading,
    oauthAccessToken,
    cloudRegion,
    projectId,
    loginWithOAuth,
    logout,
    refreshAccessToken,
    initializeAuth,
  } = useAuthStore();

  return {
    // State
    isAuthenticated,
    isLoading,
    accessToken: oauthAccessToken,
    cloudRegion,
    projectId,

    // Methods
    login: loginWithOAuth,
    logout,
    refresh: refreshAccessToken,
    initialize: initializeAuth,
  };
}
