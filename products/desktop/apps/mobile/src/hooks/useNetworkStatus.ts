import NetInfo from "@react-native-community/netinfo";
import { useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

const OFFLINE_RECOVERY_POLL_INTERVAL_MS = 5_000;

type NetworkSnapshot = {
  isConnected: boolean | null;
  isInternetReachable?: boolean | null;
};

export function hasInternetConnection(state: NetworkSnapshot): boolean {
  if (state.isConnected === false) {
    return false;
  }

  if (state.isInternetReachable === false) {
    return false;
  }

  return true;
}

export function useNetworkStatus() {
  const [isConnected, setIsConnected] = useState(true);
  const isConnectedRef = useRef(isConnected);

  useEffect(() => {
    isConnectedRef.current = isConnected;
  }, [isConnected]);

  useEffect(() => {
    let isMounted = true;
    let recoveryPoller: ReturnType<typeof setInterval> | null = null;

    const stopRecoveryPoller = () => {
      if (!recoveryPoller) {
        return;
      }

      clearInterval(recoveryPoller);
      recoveryPoller = null;
    };

    const startRecoveryPoller = () => {
      if (recoveryPoller) {
        return;
      }

      recoveryPoller = setInterval(() => {
        if (isConnectedRef.current) {
          stopRecoveryPoller();
          return;
        }

        void refreshStatus();
      }, OFFLINE_RECOVERY_POLL_INTERVAL_MS);
    };

    const applyStatus = (state: NetworkSnapshot) => {
      if (!isMounted) {
        return;
      }

      const nextIsConnected = hasInternetConnection(state);
      isConnectedRef.current = nextIsConnected;
      setIsConnected(nextIsConnected);

      if (nextIsConnected) {
        stopRecoveryPoller();
      } else {
        startRecoveryPoller();
      }
    };

    const refreshStatus = async () => {
      try {
        const state = await NetInfo.fetch();
        applyStatus(state);
      } catch {
        applyStatus({
          isConnected: false,
          isInternetReachable: false,
        });
      }
    };

    const unsubscribe = NetInfo.addEventListener((state) => {
      applyStatus(state);
    });

    const appStateSubscription = AppState.addEventListener(
      "change",
      (nextState) => {
        if (nextState === "active") {
          void refreshStatus();
        }
      },
    );

    void refreshStatus();

    return () => {
      isMounted = false;
      unsubscribe();
      appStateSubscription.remove();
      stopRecoveryPoller();
    };
  }, []);

  return { isConnected };
}
