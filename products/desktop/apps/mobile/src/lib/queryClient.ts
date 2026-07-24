import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      gcTime: 1000 * 60 * 5, // 5 minutes (formerly cacheTime)
      retry: 2,
      refetchOnWindowFocus: false, // not needed for mobile
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 1,
    },
  },
});
